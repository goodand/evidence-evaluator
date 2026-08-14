"""One-case zero-context handoff canary over the read-only vault MCP."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .providers import (
    CodexMcpServerSpec,
    ProviderError,
    run_codex_external_mcp_cli,
)


CASE_VERSION = "handoff-mcp-canary-case-v1"
GOLD_VERSION = "handoff-mcp-canary-gold-v1"
RESULT_VERSION = "handoff-mcp-canary-result-v1"
ALLOWED_TOOLS = frozenset({"vault_search", "vault_read", "vault_backlinks"})


class CanaryError(ValueError):
    """The canary inputs or observed trace violate the public contract."""


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CanaryError(f"{path} must contain one JSON object")
    return value


def _audit_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise CanaryError(f"invalid MCP audit JSONL line {number}: {exc}") from exc
        if not isinstance(record, dict):
            raise CanaryError(f"MCP audit line {number} is not an object")
        records.append(record)
    return records


def _citation_is_read(citation: dict[str, Any], reads: list[dict[str, Any]]) -> bool:
    for record in reads:
        result = record.get("result") or {}
        if (
            citation.get("path") == result.get("canonical_path")
            and isinstance(citation.get("line_start"), int)
            and isinstance(citation.get("line_end"), int)
            and result.get("line_start", 0) <= citation["line_start"]
            and citation["line_end"] <= result.get("line_end", -1)
        ):
            return True
    return False


def _claim_supported(claim: Any, reads: list[dict[str, Any]]) -> bool:
    if not isinstance(claim, dict) or not str(claim.get("text", "")).strip():
        return False
    citations = claim.get("citations")
    return (
        isinstance(citations, list)
        and bool(citations)
        and all(isinstance(item, dict) and _citation_is_read(item, reads)
                for item in citations)
    )


def _claim_uses_authority(claim: Any, authority_paths: set[str]) -> bool:
    citations = claim.get("citations") if isinstance(claim, dict) else None
    return isinstance(citations, list) and any(
        isinstance(item, dict) and item.get("path") in authority_paths
        for item in citations
    )


def assess_canary(
    case: dict[str, Any],
    gold: dict[str, Any],
    payload: dict[str, Any],
    records: list[dict[str, Any]],
    provider_meta: dict[str, Any],
    *,
    max_calls: int,
) -> dict[str, Any]:
    """Score transport, retrieval, and reconstruction without merging them."""
    if case.get("contract_version") != CASE_VERSION:
        raise CanaryError("unsupported case contract")
    if gold.get("contract_version") != GOLD_VERSION or gold.get("case_id") != case.get("id"):
        raise CanaryError("gold does not match the case")

    tools = [str(record.get("tool")) for record in records]
    errors = [record for record in records if record.get("outcome") != "ok"]
    event_summary = provider_meta.get("tool_event_summary") or {}
    forbidden = event_summary.get("forbidden") or []
    provider_tools = event_summary.get("mcp_tools")
    provider_trace_matches = (
        isinstance(provider_tools, list) and provider_tools == tools
    )
    runtime_valid = (
        1 <= len(records) <= max_calls
        and not errors
        and set(tools) <= ALLOWED_TOOLS
        and "vault_search" in tools
        and "vault_read" in tools
        and not forbidden
        and provider_trace_matches
    )

    search_paths: set[str] = set()
    reads = []
    for record in records:
        if record.get("outcome") != "ok":
            continue
        if record.get("tool") == "vault_search":
            search_paths.update((record.get("result") or {}).get("retrieved_paths") or [])
        elif record.get("tool") == "vault_read":
            reads.append(record)
    read_paths = {
        str((record.get("result") or {}).get("canonical_path")) for record in reads
    }
    required = set(gold["required_read_paths"])
    critical_recall = len(required & read_paths) / len(required) if required else 1.0
    navigation = set(gold.get("navigation_paths") or [])
    navigation_recall = (
        len(navigation & search_paths) / len(navigation) if navigation else 1.0
    )
    handoff_path = str(gold["handoff_path"])
    authority_paths = set(gold["authority_paths"])
    retrieval = {
        "handoff_discovered": handoff_path in search_paths,
        "critical_path_recall": critical_recall,
        "navigation_discovery_recall": navigation_recall,
        "exact_authority_hit": bool(authority_paths & read_paths),
        "read_paths": sorted(read_paths),
        "search_paths": sorted(search_paths),
    }

    claims = [payload.get("current_state"), payload.get("next_action")]
    stop_claims = payload.get("stop_conditions") or []
    claims.extend(stop_claims if isinstance(stop_claims, list) else [])
    citations_supported = bool(claims) and all(
        _claim_supported(claim, reads) for claim in claims
    )
    authority_support = bool(claims) and all(
        _claim_uses_authority(claim, authority_paths) for claim in claims
    )
    expected_stops = set(gold["stop_condition_codes"])
    actual_stops = set(payload.get("stop_condition_codes") or [])
    reconstruction = {
        "state_accuracy": payload.get("state_code") == gold["state_code"],
        "next_action_accuracy": payload.get("next_action_code") == gold["next_action_code"],
        "stop_condition_accuracy": actual_stops == expected_stops,
        "citations_supported_by_actual_reads": citations_supported,
        "authority_citation_present_for_every_claim": authority_support,
    }

    accepted = (
        runtime_valid
        and retrieval["handoff_discovered"]
        and retrieval["critical_path_recall"] == 1.0
        and retrieval["navigation_discovery_recall"] == 1.0
        and retrieval["exact_authority_hit"]
        and all(reconstruction.values())
    )
    return {
        "contract_version": RESULT_VERSION,
        "case_id": case["id"],
        "runtime": {
            "valid": runtime_valid,
            "mcp_call_count": len(records),
            "tools": tools,
            "provider_tools": provider_tools,
            "provider_trace_matches_audit": provider_trace_matches,
            "errors": errors,
            "forbidden_events": forbidden,
        },
        "retrieval": retrieval,
        "reconstruction": reconstruction,
        "accepted": accepted,
        "claims_not_established": [
            "arm effect",
            "multi-case generalization",
            "vault-wide recall",
            "backlink necessity",
        ],
    }


def _prompt(case: dict[str, Any], *, output_k: int, max_calls: int) -> str:
    return f"""You are a zero-context continuation agent. You know no prior chat.
Use only the three tools on the evidence-vault MCP server. Do not use shell,
native file tools, web search, user configuration, or another MCP server.

First call vault_search with this complete question and output_k={output_k}:
{case['question']}

Then call vault_read for the handoff and every authority document needed to
support current state, next action, and stop conditions. vault_backlinks is
optional. You have at most {max_calls} total MCP calls. Search previews are not
citations. Cite only line ranges you actually received from vault_read. Return
the required JSON. Do not claim absence from a zero-result or review_required
search.
"""


def run_canary(
    *,
    profile_path: Path,
    case_path: Path,
    gold_path: Path,
    schema_path: Path,
    model: str,
    output_path: Path,
    reasoning_effort: str = "medium",
    timeout_seconds: int = 600,
    max_calls: int = 6,
    output_k: int = 3,
    provider: Callable[..., dict[str, Any]] = run_codex_external_mcp_cli,
) -> dict[str, Any]:
    case, gold = _load(case_path), _load(gold_path)
    output_path = output_path.expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    audit_path = output_path.with_suffix(".mcp-audit.jsonl")
    raw_path = output_path.with_suffix(".provider.jsonl")
    for path in (output_path, audit_path, raw_path):
        if path.exists():
            raise CanaryError(f"refusing to overwrite {path}")

    repo_root = Path(__file__).resolve().parents[1]
    launcher = repo_root / "scripts" / "run_obsidian_vault_mcp.sh"
    with tempfile.TemporaryDirectory(prefix="handoff-mcp-subject-") as temp:
        subject = Path(temp)
        subject_schema = subject / "output.schema.json"
        shutil.copyfile(schema_path, subject_schema)
        server = CodexMcpServerSpec(
            name="evidence_vault",
            command=str(launcher),
            args=(),
            env={
                "EVIDENCE_VAULT_PROFILE": str(profile_path.expanduser().resolve()),
                "EVIDENCE_MCP_AUDIT_LOG": str(audit_path),
                "EVIDENCE_MCP_MAX_CALLS": str(max_calls),
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            enabled_tools=tuple(sorted(ALLOWED_TOOLS)),
        )
        try:
            observed = provider(
                subject,
                _prompt(case, output_k=output_k, max_calls=max_calls),
                subject_schema,
                {
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "timeout_seconds": timeout_seconds,
                    "approval_policy": "never",
                },
                server=server,
                run_name=case["id"],
            )
        except ProviderError as exc:
            if exc.raw:
                raw_path.write_text(exc.raw, encoding="utf-8")
            result = {
                "contract_version": RESULT_VERSION,
                "case_id": case.get("id"),
                "runtime": {"valid": False, "provider_error": str(exc)},
                "retrieval": None,
                "reconstruction": None,
                "accepted": False,
                "invalid_run": True,
            }
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
            return result

    raw_path.write_text(observed["raw"], encoding="utf-8")
    result = assess_canary(
        case,
        gold,
        observed["payload"],
        _audit_records(audit_path),
        observed["provider_meta"],
        max_calls=max_calls,
    )
    result["subject_response"] = observed["payload"]
    result["provider_meta"] = observed["provider_meta"]
    result["provenance"] = {
        "case_sha256": hashlib.sha256(case_path.read_bytes()).hexdigest(),
        "gold_sha256": hashlib.sha256(gold_path.read_bytes()).hexdigest(),
        "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "mcp_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
    }
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_schema = (
        Path(__file__).resolve().parents[1]
        / "examples"
        / "handoff-canary-output.schema.json"
    )
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--schema", type=Path, default=default_schema)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reasoning-effort", default="medium")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--max-calls", type=int, default=6)
    parser.add_argument("--output-k", type=int, default=3)
    args = parser.parse_args(argv)
    result = run_canary(
        profile_path=args.profile,
        case_path=args.case,
        gold_path=args.gold,
        schema_path=args.schema,
        model=args.model,
        output_path=args.output,
        reasoning_effort=args.reasoning_effort,
        timeout_seconds=args.timeout_seconds,
        max_calls=args.max_calls,
        output_k=args.output_k,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("invalid_run"):
        return 2
    return 0 if result.get("accepted") else 1


if __name__ == "__main__":
    raise SystemExit(main())
