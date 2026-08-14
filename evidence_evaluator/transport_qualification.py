"""Build and verify an append-only current-harness transport qualification."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .freeze import canonical_digest, sha256_file


CONTRACT_VERSION = "handoff-transport-requalification-v1"
EXPECTED_CASE_IDS = tuple(f"CONF-{number:02d}" for number in range(1, 7))
TRANSPORT_SURFACE = (
    "evidence_evaluator/handoff_canary.py",
    "evidence_evaluator/providers.py",
    "evidence_evaluator/transport_qualification.py",
    "evidence_evaluator/retrieval/corpus.py",
    "evidence_evaluator/retrieval/obsidian.py",
    "evidence_evaluator/retrieval/profile.py",
    "evidence_evaluator/retrieval/retriever.py",
    "evidence_evaluator/retrieval/service.py",
    "evidence_evaluator/retrieval/mcp_server.py",
    "examples/handoff-canary-output.schema.json",
    "scripts/run_obsidian_vault_mcp.sh",
)


class QualificationError(ValueError):
    """The transport qualification inputs or receipt are invalid."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise QualificationError(f"{path} must contain one JSON object")
    return value


def _verify_frozen_assets(root: Path) -> tuple[str | None, list[str]]:
    freeze = _load(root / "freeze.json")
    failures: list[str] = []
    claimed = freeze.get("freeze_digest")
    unsigned = {key: value for key, value in freeze.items() if key != "freeze_digest"}
    if claimed != canonical_digest(unsigned):
        failures.append("historical freeze receipt digest mismatch")
    expected = freeze.get("assets") or {}
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "freeze.json"
    }
    if actual != set(expected):
        failures.append("frozen private asset path set changed")
    for relative, digest in expected.items():
        path = root / relative
        if not path.is_file() or sha256_file(path) != digest:
            failures.append(f"frozen private asset drift: {relative}")
    return claimed if isinstance(claimed, str) else None, failures


def build_receipt(
    confirmatory_dir: Path,
    repo_root: Path,
    results_dir: Path,
    *,
    result_prefix: str,
    subject_model: str,
) -> dict[str, Any]:
    confirmatory_dir = confirmatory_dir.resolve()
    repo_root = repo_root.resolve()
    results_dir = results_dir.resolve()
    historical_digest, failures = _verify_frozen_assets(confirmatory_dir)
    paths = sorted(results_dir.glob(f"{result_prefix}-CONF-*.json"))
    rows: list[dict[str, Any]] = []
    seen: list[str] = []
    for path in paths:
        result = _load(path)
        case_id = str(result.get("case_id"))
        seen.append(case_id)
        audit_path = path.with_suffix(".mcp-audit.jsonl")
        case_path = confirmatory_dir / "cases" / f"{case_id}.json"
        gold_path = confirmatory_dir / "gold" / f"{case_id}.json"
        profile_path = confirmatory_dir / "profile.json"
        provenance = result.get("provenance") or {}
        execution = result.get("execution") or {}
        runtime = result.get("runtime") or {}
        row_failures: list[str] = []
        if result.get("accepted") is not True:
            row_failures.append("not accepted")
        if result.get("invalid_run") is True or runtime.get("valid") is not True:
            row_failures.append("invalid runtime")
        if runtime.get("provider_trace_matches_audit") is not True:
            row_failures.append("provider/server trace mismatch")
        if execution.get("subject_model") != subject_model:
            row_failures.append("subject model mismatch")
        expected_sources = {
            "case_sha256": case_path,
            "gold_sha256": gold_path,
            "profile_sha256": profile_path,
            "mcp_audit_sha256": audit_path,
        }
        for key, source in expected_sources.items():
            if not source.is_file() or provenance.get(key) != sha256_file(source):
                row_failures.append(f"provenance mismatch: {key}")
        if row_failures:
            failures.extend(f"{case_id}: {failure}" for failure in row_failures)
        rows.append({
            "case_id": case_id,
            "result_path": path.relative_to(results_dir).as_posix(),
            "result_sha256": sha256_file(path),
            "audit_path": audit_path.relative_to(results_dir).as_posix(),
            "audit_sha256": sha256_file(audit_path) if audit_path.is_file() else None,
            "accepted": result.get("accepted") is True,
            "runtime_valid": runtime.get("valid") is True,
            "provider_attempt_count": runtime.get("provider_attempt_count"),
            "failed_provider_tools": runtime.get("provider_failed_tools") or [],
        })
    if tuple(sorted(seen)) != EXPECTED_CASE_IDS or len(seen) != len(set(seen)):
        failures.append("result set is not exactly CONF-01..CONF-06")

    surface: dict[str, str] = {}
    for relative in TRANSPORT_SURFACE:
        path = repo_root / relative
        if not path.is_file():
            failures.append(f"missing transport surface: {relative}")
        else:
            surface[relative] = sha256_file(path)

    unsigned = {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if not failures else "FAIL",
        "historical_input_freeze_digest": historical_digest,
        "subject_model": subject_model,
        "result_prefix": result_prefix,
        "accepted_count": sum(row["accepted"] for row in rows),
        "invalid_run_count": sum(not row["runtime_valid"] for row in rows),
        "transport_surface": surface,
        "results": rows,
        "failures": failures,
    }
    return {**unsigned, "receipt_digest": canonical_digest(unsigned)}


def write_receipt(receipt: dict[str, Any], output: Path) -> None:
    if receipt.get("status") != "PASS":
        raise QualificationError("refusing to write a failed qualification receipt")
    output = output.resolve()
    if output.exists():
        raise QualificationError(f"refusing to overwrite append-only receipt {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def verify_receipt(
    receipt_path: Path,
    confirmatory_dir: Path,
    repo_root: Path,
    results_dir: Path,
) -> dict[str, Any]:
    expected = _load(receipt_path)
    actual = build_receipt(
        confirmatory_dir,
        repo_root,
        results_dir,
        result_prefix=str(expected.get("result_prefix", "")),
        subject_model=str(expected.get("subject_model", "")),
    )
    failures = [] if expected == actual else ["receipt or qualified inputs drifted"]
    return {
        "status": "PASS" if not failures else "FAIL",
        "receipt_digest": expected.get("receipt_digest"),
        "failures": failures,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("create", "verify"))
    parser.add_argument("--confirmatory-dir", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--result-prefix")
    parser.add_argument("--model")
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]
    try:
        if args.command == "create":
            if not args.result_prefix or not args.model:
                raise QualificationError("create requires --result-prefix and --model")
            receipt = build_receipt(
                args.confirmatory_dir,
                repo_root,
                args.results_dir,
                result_prefix=args.result_prefix,
                subject_model=args.model,
            )
            write_receipt(receipt, args.output)
            result = receipt
        else:
            result = verify_receipt(
                args.output,
                args.confirmatory_dir,
                repo_root,
                args.results_dir,
            )
    except (OSError, json.JSONDecodeError, QualificationError) as exc:
        result = {"status": "FAIL", "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
