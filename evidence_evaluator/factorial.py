"""Run the staged handoff workflow/subagent factorial experiment.

The six-case confirmatory set qualifies transport only. Performance starts on
an independent development split, then moves to a held-out split without
changing the frozen harness or evaluation assets.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from .contract import (
    SUBAGENT_VERSION,
    TRACE_VERSION,
    ContractError,
    validate_subagent_output,
    validate_trace,
)
from .evaluator import evaluate
from .factorial_design import (
    ARMS,
    RUN_VERSION,
    DesignError,
    build_freeze,
    load_cases_and_gold,
    load_json,
    load_manifest,
    qualify_existing_set,
    resolve_manifest_path,
    score_rows,
    verify_freeze,
)
from .factorial_runtime import (
    HELPER_RETRIEVAL_BUDGET,
    MAIN_RETRIEVAL_BUDGET,
    FactorialHostState,
    ToolServer,
)
from .providers import ProviderError, run_codex_mcp_cli, validate_against_schema
from .retrieval.profile import VaultProfile
from .retrieval.service import RetrievalService

ANSWER_VERSION = "handoff-factorial-answer-v1"
SUBAGENT_SCHEMA_NAME = "handoff-factorial-subagent.schema.json"
ANSWER_SCHEMA_NAME = "handoff-factorial-output.schema.json"

Provider = Callable[..., dict[str, Any]]


def _codex_usage_summary(raw: str) -> dict[str, int]:
    """Extract final structured usage without changing the provider contract."""
    final: dict[str, int] = {}
    for line in raw.split("\n-- STDERR --\n", 1)[0].splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "turn.completed":
            continue
        usage = event.get("usage")
        if isinstance(usage, dict):
            final = {
                key: int(usage.get(key, 0))
                for key in (
                    "input_tokens", "cached_input_tokens", "output_tokens",
                    "reasoning_output_tokens", "cache_write_input_tokens",
                )
            }
    return final


def _write_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise DesignError(f"refusing to overwrite append-only artifact {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _schema(repo_root: Path, name: str) -> tuple[Path, dict[str, Any]]:
    path = repo_root / "examples" / name
    return path, load_json(path)


def _provider_config(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": manifest["model"],
        "reasoning_effort": manifest.get("reasoning_effort", "medium"),
        "timeout_seconds": int(manifest.get("timeout_seconds", 600)),
        "approval_policy": "never",
        "auto_approve_mcp": True,
    }


def _main_prompt(case: dict[str, Any], arm: str) -> str:
    static = arm.endswith("STATIC")
    policy = (
        "This is the STATIC arm. Call status first and then perform exactly the "
        "static_next action returned by the host. The first search query must be "
        "the public query verbatim; the second must be a distinct reformulation. "
        "Never skip or reorder a static action."
        if static else
        "This is the DYNAMIC arm. Choose each next action from observed evidence. "
        "Do not finish until the host recall-first guard accepts the terminal action."
    )
    entry = (
        f"Public handoff path: {case['handoff_path']}"
        if case.get("condition") == "direct-handoff" else
        "The handoff path must be discovered."
    )
    return f"""You are a fresh zero-context continuation subject.
Use only the handoff_action MCP tool. Native files, shell, web, prior sessions,
gold, evaluator state, and earlier results are unavailable. The host owns the
search corpus and records every candidate and read range.

Public case ID: {case['id']}
Public question: {case['query']}
Entry condition: {case['condition']}
{entry}
{policy}

Actions are search, expand_candidates, read_candidate, follow_link, status,
and finish. You have at most {MAIN_RETRIEVAL_BUDGET} retrieval actions; finish
is separate. Search previews and helper candidates are navigation only. Read
canonical Markdown yourself before citing it. Call finish with answer or
abstain before returning JSON. Every claim support range must be within a host
read returned to this process. Return only the required JSON for arm {arm}.
"""


def _helper_prompt(case: dict[str, Any]) -> str:
    return f"""You are a fresh retrieval-only helper. Use only handoff_action.
Find candidate Markdown paths for the public question below. You may search,
expand, follow links, and read, with at most {HELPER_RETRIEVAL_BUDGET} retrieval
actions. Do not decide current state, authority, answer, next action, or stop
condition. Return only candidate_paths, host-observed read_ranges, a factual
search_trace, and uncertainty using the required schema.

Case ID: {case['id']}
Question: {case['query']}
"""


def _temp_subject(prefix: str) -> tempfile.TemporaryDirectory[str]:
    # macOS AF_UNIX paths are short. The ambient TMPDIR can exceed the limit.
    return tempfile.TemporaryDirectory(prefix=prefix, dir="/private/tmp")


def _invoke(
    provider: Provider,
    *,
    service: RetrievalService,
    case: dict[str, Any],
    static: bool,
    guard_enabled: bool,
    max_actions: int,
    prompt: str,
    schema_path: Path,
    schema: dict[str, Any],
    config: dict[str, Any],
    run_name: str,
    repo_root: Path,
    initial_candidates: list[str] | None = None,
) -> tuple[dict[str, Any], FactorialHostState, str, dict[str, Any]]:
    state = FactorialHostState(
        service,
        case,
        initial_candidates=initial_candidates,
        static=static,
        guard_enabled=guard_enabled,
        max_retrieval_actions=max_actions,
        output_k=3,
        candidate_pool_k=50,
    )
    with _temp_subject("hfactor-") as temp:
        subject = Path(temp)
        local_schema = subject / schema_path.name
        shutil.copyfile(schema_path, local_schema)
        socket_path = subject / "tool.sock"
        with ToolServer(socket_path, state):
            observed = provider(
                subject,
                socket_path,
                prompt,
                local_schema.name,
                config,
                project_root=repo_root,
                host_control=subject,
                run_name=run_name,
            )
        payload = observed["payload"]
        validate_against_schema(payload, schema)
        return (
            payload,
            state,
            str(observed.get("raw", "")),
            dict(observed.get("provider_meta") or {}),
        )


def run_helper(
    *,
    service: RetrievalService,
    case: dict[str, Any],
    manifest: dict[str, Any],
    repo_root: Path,
    provider: Provider = run_codex_mcp_cli,
) -> dict[str, Any]:
    schema_path, schema = _schema(repo_root, SUBAGENT_SCHEMA_NAME)
    payload, state, raw, provider_meta = _invoke(
        provider,
        service=service,
        case=case,
        static=False,
        guard_enabled=False,
        max_actions=HELPER_RETRIEVAL_BUDGET,
        prompt=_helper_prompt(case),
        schema_path=schema_path,
        schema=schema,
        config=_provider_config(manifest),
        run_name=f"helper-{case['id']}",
        repo_root=repo_root,
    )
    provider_meta = {**provider_meta, "usage": _codex_usage_summary(raw)}
    try:
        validated = validate_subagent_output(payload)
        observed_candidates = set(state.candidates)
        if not set(validated["candidate_paths"]) <= observed_candidates:
            raise ContractError("C3: helper returned an unobserved candidate path")
        for item in validated["search_trace"]:
            if not set(item["result_paths"]) <= observed_candidates:
                raise ContractError("C3: helper search trace names an unobserved path")
        observed_actions = {
            "search" if item["action"] == "reformulate_query" else item["action"]
            for item in state.actions
        }
        claimed_actions = {item["action"] for item in validated["search_trace"]}
        if not claimed_actions <= observed_actions:
            raise ContractError("C3: helper search trace names an unobserved action")
        observed_reads = {
            (item["path"], item["start"], item["end"]) for item in state.reads
        }
        claimed_reads = {
            (item["path"], item["start"], item["end"])
            for item in validated["read_ranges"]
        }
        if not claimed_reads <= observed_reads:
            raise ContractError("C3: helper returned an unobserved read range")
    except ContractError as exc:
        return {
            "contract_version": SUBAGENT_VERSION,
            "valid": False,
            "failure_code": "C3",
            "error": str(exc),
            "payload": payload,
            "host_trace": state.trace_fields(),
            "provider_meta": provider_meta,
            "raw": raw,
        }
    return {
        "contract_version": SUBAGENT_VERSION,
        "valid": True,
        "payload": validated,
        "host_trace": state.trace_fields(),
        "provider_meta": provider_meta,
        "raw": raw,
    }


def _trace_from_payload(
    case: dict[str, Any],
    arm: str,
    payload: dict[str, Any],
    state: FactorialHostState,
    helper: dict[str, Any] | None,
) -> dict[str, Any]:
    fields = state.trace_fields()
    failures = list(fields["failure_codes"])
    if payload.get("contract_version") != ANSWER_VERSION:
        failures.append("V1")
    if payload.get("case_id") != case["id"] or payload.get("arm") != arm:
        failures.append("V1")
    if payload.get("terminal_action") != fields["stop_reason"]:
        failures.append("V1")
    if helper and not helper.get("valid"):
        failures.append("C3")
    trace = {
        "contract_version": TRACE_VERSION,
        "case_id": case["id"],
        "arm": arm,
        "subagent_output": (helper or {}).get("payload"),
        **fields,
        "failure_codes": list(dict.fromkeys(failures)),
        "claims": payload.get("claims", []),
        "answer_text": payload.get("answer_text", ""),
        "current_state": payload.get("current_state", ""),
        "next_action": payload.get("next_action", ""),
        "stop_conditions": payload.get("stop_conditions", []),
        "recommended_actions": payload.get("recommended_actions", []),
        "uncertainties": payload.get("uncertainties", []),
        "declared_absent": payload.get("declared_absent", False),
    }
    try:
        validate_trace(trace)
    except ContractError as exc:
        trace["tool_errors"].append(str(exc))
        if "C2" in str(exc):
            trace["failure_codes"].append("C2")
        else:
            trace["failure_codes"].append("E1")
    trace["failure_codes"] = list(dict.fromkeys(trace["failure_codes"]))
    return trace


def run_cell(
    *,
    service: RetrievalService,
    case: dict[str, Any],
    gold: dict[str, Any],
    arm: str,
    replicate: int,
    manifest: dict[str, Any],
    repo_root: Path,
    helper: dict[str, Any] | None = None,
    provider: Provider = run_codex_mcp_cli,
) -> dict[str, Any]:
    if arm not in ARMS:
        raise DesignError(f"unknown arm {arm}")
    needs_helper = arm.startswith("R_")
    if needs_helper != (helper is not None):
        raise DesignError("R arms require one helper packet; S arms forbid it")
    if needs_helper and not helper.get("valid"):
        trace = {
            "contract_version": TRACE_VERSION,
            "case_id": case["id"],
            "arm": arm,
            "subagent_output": helper.get("payload"),
            "actions": [], "reads": [], "claims": [],
            "current_state": "", "next_action": "", "stop_conditions": [],
            "uncertainties": [], "recommended_actions": [], "answer_text": "",
            "declared_absent": False, "guard_rejections": [],
            "failure_codes": ["C3", "V1"],
            "tool_errors": [str(helper.get("error", "invalid helper packet"))],
            "stop_reason": "V1", "n_search": 0, "n_read": 0,
            "retrieval_actions": 0, "wall_clock_ms": 0,
        }
        score = evaluate(trace, gold, case)
        score.update({
            "contract_version": RUN_VERSION, "replicate": replicate,
            "is_absent": gold["is_absent"], "correct_abstention": False,
            "premature_stop": False, "retrieval_actions": 0,
        })
        return {
            "contract_version": RUN_VERSION, "case_id": case["id"],
            "arm": arm, "replicate": replicate, "trace": trace,
            "score": score, "subject_response": {}, "provider_meta": {}, "raw": "",
        }
    schema_path, schema = _schema(repo_root, ANSWER_SCHEMA_NAME)
    try:
        payload, state, raw, provider_meta = _invoke(
            provider,
            service=service,
            case=case,
            static=arm.endswith("STATIC"),
            guard_enabled=True,
            max_actions=MAIN_RETRIEVAL_BUDGET,
            prompt=_main_prompt(case, arm),
            schema_path=schema_path,
            schema=schema,
            config=_provider_config(manifest),
            run_name=f"{case['id']}-{arm}-r{replicate}",
            repo_root=repo_root,
            initial_candidates=(helper or {}).get("payload", {}).get("candidate_paths"),
        )
        provider_meta = {**provider_meta, "usage": _codex_usage_summary(raw)}
        trace = _trace_from_payload(case, arm, payload, state, helper)
    except (ProviderError, ContractError) as exc:
        payload = {}
        raw = getattr(exc, "raw", "")
        provider_meta = getattr(exc, "provider_meta", {})
        trace = {
            "contract_version": TRACE_VERSION,
            "case_id": case["id"],
            "arm": arm,
            "subagent_output": (helper or {}).get("payload"),
            "actions": [],
            "reads": [],
            "claims": [],
            "current_state": "",
            "next_action": "",
            "stop_conditions": [],
            "uncertainties": [],
            "tool_errors": [str(exc)],
            "stop_reason": "V1",
            "recommended_actions": [],
            "answer_text": "",
            "declared_absent": False,
            "guard_rejections": [],
            "failure_codes": ["V1"],
            "n_search": 0,
            "n_read": 0,
            "retrieval_actions": 0,
            "wall_clock_ms": 0,
        }
    score = evaluate(trace, gold, case)
    main_usage = dict(provider_meta.get("usage") or {})
    helper_usage = dict(((helper or {}).get("provider_meta") or {}).get("usage") or {})
    score.update({
        "contract_version": RUN_VERSION,
        "replicate": replicate,
        "is_absent": gold["is_absent"],
        "correct_abstention": bool(
            gold["is_absent"] and trace.get("declared_absent")
            and not score["invalid_run"]
        ),
        "premature_stop": "C1" in trace["failure_codes"],
        "retrieval_actions": trace.get("retrieval_actions", 0),
        "main_input_tokens": int(main_usage.get("input_tokens", 0)),
        "helper_input_tokens": int(helper_usage.get("input_tokens", 0)),
        "total_input_tokens": int(main_usage.get("input_tokens", 0))
        + int(helper_usage.get("input_tokens", 0)),
        "main_output_tokens": int(main_usage.get("output_tokens", 0)),
        "helper_output_tokens": int(helper_usage.get("output_tokens", 0)),
        "total_output_tokens": int(main_usage.get("output_tokens", 0))
        + int(helper_usage.get("output_tokens", 0)),
    })
    return {
        "contract_version": RUN_VERSION,
        "case_id": case["id"],
        "arm": arm,
        "replicate": replicate,
        "trace": trace,
        "score": score,
        "subject_response": payload,
        "provider_meta": provider_meta,
        "raw": raw,
    }


def _arm_order(case_id: str, replicate: int, arms: tuple[str, ...]) -> list[str]:
    return sorted(
        arms,
        key=lambda arm: hashlib.sha256(
            f"{case_id}:{replicate}:{arm}".encode("utf-8")
        ).hexdigest(),
    )


def _load_service(manifest_path: Path, manifest: dict[str, Any]) -> RetrievalService:
    profile_path = resolve_manifest_path(manifest_path, manifest["profile"])
    return RetrievalService.from_profile(VaultProfile.from_json(profile_path))


def _run_stage(
    *,
    stage: str,
    manifest_path: Path,
    freeze_path: Path,
    output_dir: Path,
    repo_root: Path,
    provider: Provider = run_codex_mcp_cli,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    freeze_status = verify_freeze(manifest_path, repo_root, freeze_path)
    if freeze_status["status"] != "PASS":
        raise DesignError(f"frozen surface is stale: {freeze_status['failures']}")
    cases, gold = load_cases_and_gold(manifest_path)
    service = _load_service(manifest_path, manifest)

    if stage == "screen":
        case_ids = manifest["splits"]["development"]
        arms = ("S_STATIC", "S_DYNAMIC")
        replicates = (1,)
    elif stage == "confirm":
        screen_path = output_dir / "screen-summary.json"
        screen = load_json(screen_path)
        expected_screen_paths = {
            output_dir / f"screen-{case_id}-{arm}-r1.json"
            for case_id in manifest["splits"]["development"]
            for arm in ("S_STATIC", "S_DYNAMIC")
        }
        actual_screen_paths = set(output_dir.glob("screen-DEV-*-S_*-r1.json"))
        if actual_screen_paths != expected_screen_paths:
            raise DesignError("screen artifact matrix is incomplete or contains extras")
        screen_rows = [load_json(path)["score"] for path in sorted(actual_screen_paths)]
        recomputed_screen = score_rows(screen_rows, stage="screen")
        recomputed_screen["freeze_digest"] = freeze_status["freeze_digest"]
        if screen != recomputed_screen:
            raise DesignError("screen summary does not match its append-only cell artifacts")
        decision = (screen.get("screen_gate") or {}).get("decision")
        if decision == "FULL_2X2":
            arms = ARMS
        elif decision == "STATIC_SUBAGENT_ONLY":
            arms = ("S_STATIC", "R_STATIC")
        else:
            raise DesignError("screen summary has no valid preregistered decision")
        case_ids = manifest["splits"]["held_out"]
        replicates = (1, 2, 3)
    else:
        raise DesignError(f"unsupported stage {stage}")

    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for replicate in replicates:
        for case_id in case_ids:
            helper: dict[str, Any] | None = None
            if any(arm.startswith("R_") for arm in arms):
                helper_path = output_dir / f"{stage}-{case_id}-r{replicate}-helper.json"
                helper = run_helper(
                    service=service,
                    case=cases[case_id],
                    manifest=manifest,
                    repo_root=repo_root,
                    provider=provider,
                )
                _write_new(helper_path, helper)
            for arm in _arm_order(case_id, replicate, arms):
                artifact = run_cell(
                    service=service,
                    case=cases[case_id],
                    gold=gold[case_id],
                    arm=arm,
                    replicate=replicate,
                    manifest=manifest,
                    repo_root=repo_root,
                    helper=helper if arm.startswith("R_") else None,
                    provider=provider,
                )
                path = output_dir / f"{stage}-{case_id}-{arm}-r{replicate}.json"
                _write_new(path, artifact)
                rows.append(artifact["score"])
    summary = score_rows(rows, stage=stage)
    summary["freeze_digest"] = freeze_status["freeze_digest"]
    _write_new(output_dir / f"{stage}-summary.json", summary)
    return summary


def _run_canary(
    *,
    manifest_path: Path,
    freeze_path: Path,
    output_path: Path,
    case_id: str,
    arm: str,
    repo_root: Path,
    provider: Provider = run_codex_mcp_cli,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    freeze_status = verify_freeze(manifest_path, repo_root, freeze_path)
    if freeze_status["status"] != "PASS":
        raise DesignError(f"frozen surface is stale: {freeze_status['failures']}")
    cases, gold = load_cases_and_gold(manifest_path)
    if case_id not in manifest["splits"]["development"]:
        raise DesignError("canary must use a development case, never held-out")
    if arm not in ARMS:
        raise DesignError(f"unknown canary arm {arm}")
    service = _load_service(manifest_path, manifest)
    helper = None
    if arm.startswith("R_"):
        helper = run_helper(
            service=service,
            case=cases[case_id],
            manifest=manifest,
            repo_root=repo_root,
            provider=provider,
        )
    artifact = run_cell(
        service=service,
        case=cases[case_id],
        gold=gold[case_id],
        arm=arm,
        replicate=1,
        manifest=manifest,
        repo_root=repo_root,
        helper=helper,
        provider=provider,
    )
    artifact["kind"] = "handoff-factorial-development-canary-v2"
    artifact["freeze_digest"] = freeze_status["freeze_digest"]
    artifact["claims_not_established"] = [
        "controller effect", "subagent effect", "interaction", "held-out performance",
    ]
    _write_new(output_path, artifact)
    return artifact


def score_directory(output_dir: Path, stage: str) -> dict[str, Any]:
    rows = [
        load_json(path)["score"]
        for path in sorted(output_dir.glob(f"{stage}-*-*-r*.json"))
        if not path.name.endswith("-helper.json")
    ]
    return score_rows(rows, stage=stage)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    qualify = sub.add_parser("qualify")
    qualify.add_argument("--confirmatory-dir", type=Path, required=True)
    qualify.add_argument("--results-dir", type=Path, default=Path("results"))

    freeze = sub.add_parser("freeze")
    freeze.add_argument("--manifest", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--verify", action="store_true")

    canary = sub.add_parser("canary")
    canary.add_argument("--manifest", type=Path, required=True)
    canary.add_argument("--freeze", type=Path, required=True)
    canary.add_argument("--case-id", required=True)
    canary.add_argument("--arm", choices=ARMS, required=True)
    canary.add_argument("--output", type=Path, required=True)

    for name in ("screen", "confirm"):
        command = sub.add_parser(name)
        command.add_argument("--manifest", type=Path, required=True)
        command.add_argument("--freeze", type=Path, required=True)
        command.add_argument("--output-dir", type=Path, required=True)

    score = sub.add_parser("score")
    score.add_argument("--output-dir", type=Path, required=True)
    score.add_argument("--stage", choices=("screen", "confirm"), required=True)
    args = parser.parse_args(argv)
    repo_root = Path(__file__).resolve().parents[1]

    try:
        if args.command == "qualify":
            result = qualify_existing_set(
                args.confirmatory_dir, repo_root, args.results_dir)
        elif args.command == "freeze":
            if args.verify:
                result = verify_freeze(args.manifest, repo_root, args.output)
            else:
                result = build_freeze(args.manifest, repo_root)
                _write_new(args.output, result)
        elif args.command == "canary":
            result = _run_canary(
                manifest_path=args.manifest,
                freeze_path=args.freeze,
                output_path=args.output,
                case_id=args.case_id,
                arm=args.arm,
                repo_root=repo_root,
            )
        elif args.command in {"screen", "confirm"}:
            result = _run_stage(
                stage=args.command,
                manifest_path=args.manifest,
                freeze_path=args.freeze,
                output_dir=args.output_dir,
                repo_root=repo_root,
            )
        else:
            result = score_directory(args.output_dir, args.stage)
    except (DesignError, ProviderError, ContractError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("status") == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
