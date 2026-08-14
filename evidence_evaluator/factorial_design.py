"""Frozen design, qualification, and paired scoring for handoff factorial v2."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .contract import validate_case, validate_gold
from .freeze import verify_tree_freeze

MANIFEST_VERSION = "handoff-factorial-manifest-v2"
FREEZE_VERSION = "handoff-factorial-freeze-v2"
RUN_VERSION = "handoff-factorial-run-v2"
SUMMARY_VERSION = "handoff-factorial-summary-v2"
ARMS = ("S_STATIC", "S_DYNAMIC", "R_STATIC", "R_DYNAMIC")
STATIC_ARMS = ("S_STATIC", "R_STATIC")
DIFFICULTIES = frozenset({
    "zero-overlap-graph-only",
    "query-reformulation-only",
    "stale-replica",
    "dated-or-same-basename",
    "pool-outside-output-k",
    "multi-source-reconstruction",
    "natural-no-gold",
    "wrong-vault-no-gold",
})
NO_GOLD_DIFFICULTIES = frozenset({"natural-no-gold", "wrong-vault-no-gold"})
QUALIFICATION_DIGEST = (
    "5187e0e9442b70131eb8bdc440f5d6990076d44198912ae721946ef3afe3c255"
)


class DesignError(ValueError):
    """A design artifact is incomplete, stale, or internally contradictory."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise DesignError(f"{path} must contain one JSON object")
    return value


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = load_json(path)
    if manifest.get("contract_version") != MANIFEST_VERSION:
        raise DesignError("unsupported factorial manifest version")
    for key in ("experiment_id", "profile", "case_dir", "gold_dir", "model"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise DesignError(f"manifest requires non-empty {key}")
    splits = manifest.get("splits")
    if not isinstance(splits, dict):
        raise DesignError("manifest.splits must be an object")
    development = splits.get("development")
    held_out = splits.get("held_out")
    if not isinstance(development, list) or len(development) != 8:
        raise DesignError("development split must contain exactly 8 case IDs")
    if not isinstance(held_out, list) or len(held_out) != 8:
        raise DesignError("held_out split must contain exactly 8 case IDs")
    all_ids = [*development, *held_out]
    if not all(isinstance(item, str) and item for item in all_ids):
        raise DesignError("case IDs must be non-empty strings")
    if len(set(all_ids)) != 16:
        raise DesignError("development and held_out case IDs must be disjoint")
    if manifest.get("replicates", 3) != 3:
        raise DesignError("confirmatory replicates are frozen at 3")
    if manifest.get("main_retrieval_budget", 10) != 10:
        raise DesignError("main retrieval budget is frozen at 10")
    if manifest.get("helper_retrieval_budget", 4) != 4:
        raise DesignError("helper retrieval budget is frozen at 4")
    if manifest.get("output_k", 3) != 3:
        raise DesignError("output_k is frozen at 3")
    if manifest.get("candidate_pool_k", 50) != 50:
        raise DesignError("candidate_pool_k is frozen at 50")
    if manifest.get("qualification_freeze_digest") != QUALIFICATION_DIGEST:
        raise DesignError("qualification freeze digest does not match the executed set")
    return manifest


def resolve_manifest_path(manifest_path: Path, value: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = manifest_path.parent / candidate
    return candidate.resolve()


def load_cases_and_gold(
    manifest_path: Path,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = load_manifest(manifest_path)
    case_dir = resolve_manifest_path(manifest_path, manifest["case_dir"])
    gold_dir = resolve_manifest_path(manifest_path, manifest["gold_dir"])
    cases: dict[str, dict[str, Any]] = {}
    gold: dict[str, dict[str, Any]] = {}
    split_ids = [*manifest["splits"]["development"], *manifest["splits"]["held_out"]]
    for case_id in split_ids:
        case = validate_case(load_json(case_dir / f"{case_id}.json"))
        truth = validate_gold(load_json(gold_dir / f"{case_id}.json"), case)
        if case["id"] != case_id:
            raise DesignError(f"case filename/id mismatch for {case_id}")
        difficulty = case.get("difficulty")
        if difficulty not in DIFFICULTIES:
            raise DesignError(f"case {case_id} has unsupported difficulty {difficulty!r}")
        if truth["is_absent"] != (difficulty in NO_GOLD_DIFFICULTIES):
            raise DesignError(f"case {case_id} absence truth contradicts difficulty")
        cases[case_id] = case
        gold[case_id] = truth
    for split_name in ("development", "held_out"):
        observed = {cases[case_id]["difficulty"] for case_id in manifest["splits"][split_name]}
        if observed != DIFFICULTIES:
            raise DesignError(
                f"{split_name} must contain each difficulty exactly once; got {sorted(observed)}"
            )
    return cases, gold


def harness_surface(repo_root: Path) -> tuple[str, ...]:
    return (
        "evidence_evaluator/contract.py",
        "evidence_evaluator/evaluator.py",
        "evidence_evaluator/freeze.py",
        "evidence_evaluator/factorial_design.py",
        "evidence_evaluator/factorial_runtime.py",
        "evidence_evaluator/factorial.py",
        "evidence_evaluator/mcp_bridge.py",
        "evidence_evaluator/providers.py",
        "evidence_evaluator/runner.py",
        "evidence_evaluator/subject_tool.py",
        "evidence_evaluator/retrieval/corpus.py",
        "evidence_evaluator/retrieval/obsidian.py",
        "evidence_evaluator/retrieval/profile.py",
        "evidence_evaluator/retrieval/retriever.py",
        "evidence_evaluator/retrieval/service.py",
        "examples/handoff-factorial-output.schema.json",
        "examples/handoff-factorial-subagent.schema.json",
    )


def build_freeze(manifest_path: Path, repo_root: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    load_cases_and_gold(manifest_path)
    root = manifest_path.parent
    # Freeze the complete private bundle, including corpus, curator draft,
    # structural qualification, cases, and gold. Pinning only case/gold while
    # allowing corpus drift would make the same receipt describe a different
    # retrieval task.
    asset_paths = {
        path for path in root.rglob("*")
        if path.is_file() and path.name != "freeze.json"
    }
    assets = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(asset_paths)
    }
    surface = {
        relative: sha256_file(repo_root / relative)
        for relative in harness_surface(repo_root)
    }
    unsigned = {
        "contract_version": FREEZE_VERSION,
        "experiment_id": manifest["experiment_id"],
        "qualification_freeze_digest": QUALIFICATION_DIGEST,
        "assets": assets,
        "harness_surface": surface,
    }
    return {**unsigned, "freeze_digest": canonical_digest(unsigned)}


def verify_freeze(
    manifest_path: Path, repo_root: Path, freeze_path: Path
) -> dict[str, Any]:
    expected = load_json(freeze_path)
    actual = build_freeze(manifest_path, repo_root)
    failures = []
    if expected.get("contract_version") != FREEZE_VERSION:
        failures.append("unsupported freeze receipt")
    if expected.get("freeze_digest") != canonical_digest({
        key: value for key, value in expected.items() if key != "freeze_digest"
    }):
        failures.append("freeze receipt self-digest mismatch")
    if expected != actual:
        failures.append("factorial inputs or harness surface drifted")
    return {
        "status": "PASS" if not failures else "FAIL",
        "freeze_digest": expected.get("freeze_digest"),
        "failures": failures,
    }


def qualify_existing_set(root: Path, repo_root: Path, results_dir: Path) -> dict[str, Any]:
    freeze = verify_tree_freeze(root.resolve(), repo_root.resolve())
    result_paths = sorted(results_dir.glob("handoff-confirmatory-v1-CONF-*-attempt1.json"))
    accepted = 0
    invalid = 0
    ids: set[str] = set()
    for path in result_paths:
        result = load_json(path)
        ids.add(str(result.get("case_id")))
        accepted += result.get("accepted") is True
        invalid += result.get("invalid_run") is True
    expected_ids = {f"CONF-{number:02d}" for number in range(1, 7)}
    failures = list(freeze["failures"])
    if ids != expected_ids:
        failures.append("qualification result set is not exactly CONF-01..CONF-06")
    if accepted != 6 or invalid:
        failures.append(f"qualification requires accepted=6 and invalid=0; got {accepted}/{invalid}")
    if freeze.get("freeze_digest") != QUALIFICATION_DIGEST:
        failures.append("qualification digest differs from preregistered digest")
    return {
        "status": "PASS" if not failures else "FAIL",
        "accepted": accepted,
        "invalid_runs": invalid,
        "freeze_digest": freeze.get("freeze_digest"),
        "failures": failures,
    }


def _paired(rows: list[dict[str, Any]], left: str, right: str, field: str) -> list[float]:
    grouped: dict[tuple[str, int], dict[str, dict[str, Any]]] = {}
    for row in rows:
        key = (str(row["case_id"]), int(row.get("replicate", 1)))
        grouped.setdefault(key, {})[str(row["arm"])] = row
    deltas = []
    for arms in grouped.values():
        if left in arms and right in arms:
            deltas.append(float(arms[right][field]) - float(arms[left][field]))
    return deltas


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def score_rows(rows: list[dict[str, Any]], *, stage: str) -> dict[str, Any]:
    if not rows:
        raise DesignError("no result rows to score")
    positive = [row for row in rows if not row.get("is_absent")]
    absent = [row for row in rows if row.get("is_absent")]
    result: dict[str, Any] = {
        "contract_version": SUMMARY_VERSION,
        "stage": stage,
        "n_runs": len(rows),
        "invalid_run_rate": mean(row.get("invalid_run", False) for row in rows),
        "positive": {
            "n_runs": len(positive),
            "grounded_continuation_rate": mean(
                row.get("full_hard_gate", False) for row in positive),
            "critical_path_recall": mean(
                row.get("critical_path_recall", 0.0) for row in positive),
            "exact_authority_hit_rate": mean(
                row.get("exact_authority_hit", False) for row in positive),
        },
        "no_gold": {
            "n_runs": len(absent),
            "correct_abstention_rate": mean(
                row.get("correct_abstention", False) for row in absent),
            "false_absence_rate": mean(
                row.get("false_absence", False) for row in rows),
        },
        "by_arm": {},
    }
    for arm in ARMS:
        arm_rows = [row for row in rows if row["arm"] == arm]
        if arm_rows:
            result["by_arm"][arm] = {
                "n_runs": len(arm_rows),
                "grounded_continuation_rate": mean(
                    row.get("full_hard_gate", False) for row in arm_rows),
                "critical_path_recall": mean(
                    row.get("critical_path_recall", 0.0) for row in arm_rows),
                "invalid_run_rate": mean(
                    row.get("invalid_run", False) for row in arm_rows),
                "mean_retrieval_actions": mean(
                    row.get("retrieval_actions", 0) for row in arm_rows),
                "mean_wall_clock_ms": mean(
                    row.get("wall_clock_ms", 0) for row in arm_rows),
                "mean_total_input_tokens": mean(
                    row.get("total_input_tokens", 0) for row in arm_rows),
                "mean_total_output_tokens": mean(
                    row.get("total_output_tokens", 0) for row in arm_rows),
            }

    static_dynamic = _paired(rows, "S_STATIC", "S_DYNAMIC", "full_hard_gate")
    r_static_dynamic = _paired(rows, "R_STATIC", "R_DYNAMIC", "full_hard_gate")
    static_subagent = _paired(rows, "S_STATIC", "R_STATIC", "full_hard_gate")
    dynamic_subagent = _paired(rows, "S_DYNAMIC", "R_DYNAMIC", "full_hard_gate")
    result["effects"] = {
        "controller": mean([*static_dynamic, *r_static_dynamic]),
        "subagent": mean([*static_subagent, *dynamic_subagent]),
        "interaction": mean(dynamic_subagent) - mean(static_subagent),
        "paired_controller_deltas": [*static_dynamic, *r_static_dynamic],
        "paired_subagent_deltas": [*static_subagent, *dynamic_subagent],
    }
    if stage == "screen":
        pairs: dict[str, dict[str, dict[str, Any]]] = {}
        for row in rows:
            pairs.setdefault(str(row["case_id"]), {})[str(row["arm"])] = row
        improvements = 0
        regressions = 0
        for arms in pairs.values():
            if {"S_STATIC", "S_DYNAMIC"} <= set(arms):
                left = bool(arms["S_STATIC"]["full_hard_gate"])
                right = bool(arms["S_DYNAMIC"]["full_hard_gate"])
                improvements += right and not left
                regressions += left and not right
        dynamic_invalid = sum(
            row.get("invalid_run", False) for row in rows if row["arm"] == "S_DYNAMIC")
        static_invalid = sum(
            row.get("invalid_run", False) for row in rows if row["arm"] == "S_STATIC")
        false_absence = sum(row.get("false_absence", False) for row in rows)
        premature = sum(row.get("premature_stop", False) for row in rows)
        go = (
            improvements >= 2 and regressions == 0 and false_absence == 0
            and premature == 0 and dynamic_invalid - static_invalid <= 1
        )
        result["screen_gate"] = {
            "decision": "FULL_2X2" if go else "STATIC_SUBAGENT_ONLY",
            "improved_cases": improvements,
            "regressed_cases": regressions,
            "false_absence": false_absence,
            "premature_stop": premature,
            "dynamic_minus_static_invalid": dynamic_invalid - static_invalid,
        }
    return result
