from __future__ import annotations

import json
import re
import socket
import tempfile
from pathlib import Path

import pytest

from evidence_evaluator.contract import (
    CASE_VERSION,
    GOLD_VERSION,
    SUBAGENT_VERSION,
    ContractError,
    validate_subagent_output,
)
from evidence_evaluator.factorial import _run_stage, run_cell, run_helper
from evidence_evaluator.factorial_design import (
    DIFFICULTIES,
    DesignError,
    MANIFEST_VERSION,
    QUALIFICATION_DIGEST,
    build_freeze,
    load_cases_and_gold,
    score_rows,
    verify_freeze,
)
from evidence_evaluator.factorial_runtime import FactorialHostState
from evidence_evaluator.factorial import _codex_usage_summary
from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.service import RetrievalService


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _service(tmp_path: Path) -> RetrievalService:
    _write(
        tmp_path / "docs" / "Handoff.md",
        "# Handoff\nProject zephyr relay.\nSee [authority](Authority.md).\n",
    )
    _write(
        tmp_path / "docs" / "Authority.md",
        "# Authority\nSTATE_READY is current.\nNEXT_RUN_ONE is next.\nSTOP_GREEN ends work.\n",
    )
    for number in range(1, 20):
        _write(
            tmp_path / "notes" / f"Distractor-{number}.md",
            f"# Zephyr distractor {number}\nrelay archive unrelated {number}\n",
        )
    profile = VaultProfile(root=tmp_path, obsidian_enabled=False)
    return RetrievalService.from_profile(profile)


def _case(case_id: str = "DEV-01", difficulty: str = "zero-overlap-graph-only") -> dict:
    return {
        "contract_version": CASE_VERSION,
        "id": case_id,
        "query": "zephyr relay continuation",
        "condition": "direct-handoff",
        "handoff_path": "docs/Handoff.md",
        "difficulty": difficulty,
    }


def _gold(case_id: str = "DEV-01", *, absent: bool = False) -> dict:
    return {
        "contract_version": GOLD_VERSION,
        "case_id": case_id,
        "handoff_path": "docs/Handoff.md",
        "expected_paths": ["docs/Handoff.md", "docs/Authority.md"],
        "critical_paths": ["docs/Handoff.md", "docs/Authority.md"],
        "expected_authority": ["docs/Authority.md"],
        "permitted_authority_paths": ["docs/Authority.md"],
        "claims": [{
            "claim_id": "state",
            "support_ranges": [{"path": "docs/Authority.md", "start": 1, "end": 4}],
        }],
        "is_absent": absent,
        "current_state_terms": [["STATE_READY"]],
        "next_action_terms": [["NEXT_RUN_ONE"]],
        "stop_condition_terms": [["STOP_GREEN"]],
        "forbidden_terms": [],
        "safety_forbidden_terms": [],
    }


def _manifest() -> dict:
    return {
        "contract_version": MANIFEST_VERSION,
        "experiment_id": "test-factorial",
        "profile": "profile.json",
        "case_dir": "cases",
        "gold_dir": "gold",
        "model": "test-model",
        "reasoning_effort": "low",
        "timeout_seconds": 30,
        "replicates": 3,
        "main_retrieval_budget": 10,
        "helper_retrieval_budget": 4,
        "output_k": 3,
        "candidate_pool_k": 50,
        "qualification_freeze_digest": QUALIFICATION_DIGEST,
        "splits": {
            "development": [f"DEV-{number:02d}" for number in range(1, 9)],
            "held_out": [f"HOLD-{number:02d}" for number in range(1, 9)],
        },
    }


def _socket_request(socket_path: Path, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(str(socket_path))
        client.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        chunks = []
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks))


def _require_unix_socket() -> None:
    with tempfile.TemporaryDirectory(prefix="hf-cap-", dir="/private/tmp") as temp:
        probe = Path(temp) / "probe.sock"
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.bind(str(probe))
        except PermissionError:
            pytest.skip("AF_UNIX is blocked in this capability lane")
        finally:
            sock.close()


def _answer(case_id: str, arm: str, terminal: str = "answer") -> dict:
    return {
        "contract_version": "handoff-factorial-answer-v1",
        "case_id": case_id,
        "arm": arm,
        "terminal_action": terminal,
        "answer_text": "STATE_READY NEXT_RUN_ONE STOP_GREEN",
        "claims": [{
            "claim_id": "state",
            "claim": "STATE_READY",
            "support": [{"path": "docs/Authority.md", "start": 1, "end": 4}],
        }],
        "current_state": "STATE_READY",
        "next_action": "NEXT_RUN_ONE",
        "stop_conditions": ["STOP_GREEN"],
        "recommended_actions": ["NEXT_RUN_ONE"],
        "uncertainties": [],
        "declared_absent": terminal == "abstain",
    }


def _dynamic_provider(subject, socket_path, prompt, schema_name, config, **kwargs):
    del subject, prompt, schema_name, config, kwargs
    _socket_request(socket_path, {
        "action": "search", "query": "zephyr relay continuation"})
    _socket_request(socket_path, {
        "action": "search", "query": "project authority current next stop"})
    expanded = _socket_request(socket_path, {"action": "expand_candidates"})
    assert len(expanded["result_paths"]) <= 12
    assert expanded["result_path_count"] >= len(expanded["result_paths"])
    authority = "docs/Authority.md"
    _socket_request(socket_path, {
        "action": "read_candidate", "path": "docs/Handoff.md", "start": 1, "end": 4})
    _socket_request(socket_path, {"action": "follow_link", "path": "docs/Handoff.md"})
    _socket_request(socket_path, {
        "action": "read_candidate", "path": authority, "start": 1, "end": 4})
    _socket_request(socket_path, {
        "action": "read_candidate", "path": "notes/Distractor-2.md",
        "start": 1, "end": 2})
    _socket_request(socket_path, {"action": "finish", "terminal_action": "answer"})
    return {
        "payload": _answer("DEV-01", "S_DYNAMIC"),
        "raw": "scripted",
        "provider_meta": {"provider": "scripted"},
    }


def _static_provider(subject, socket_path, prompt, schema_name, config, **kwargs):
    del subject, prompt, schema_name, config, kwargs
    searches = 0
    while True:
        status = _socket_request(socket_path, {"action": "status"})
        step = status["static_next"]
        action = step["action"]
        if action == "search":
            query = ("zephyr relay continuation" if searches == 0
                     else "project authority current next stop")
            searches += 1
            response = _socket_request(socket_path, {"action": "search", "query": query})
        elif action in {"read_candidate", "follow_link"}:
            response = _socket_request(
                socket_path, {"action": action, "path": step["path"], "start": 1, "end": 4})
        elif action == "expand_candidates":
            response = _socket_request(socket_path, {"action": action})
        else:
            response = _socket_request(
                socket_path, {"action": "finish", "terminal_action": "answer"})
            assert response["ok"] is True
            break
        assert response["ok"] is True
    return {
        "payload": _answer("DEV-01", "S_STATIC"),
        "raw": "scripted",
        "provider_meta": {"provider": "scripted"},
    }


def test_static_runtime_rejects_reordered_action(tmp_path: Path) -> None:
    state = FactorialHostState(
        _service(tmp_path), _case(), static=True, guard_enabled=True)
    result = state.dispatch({"action": "expand_candidates"})
    assert result["ok"] is False
    assert "V1" in state.failure_codes


def test_dynamic_cell_runs_through_real_socket_and_host_trace(tmp_path: Path) -> None:
    _require_unix_socket()
    result = run_cell(
        service=_service(tmp_path),
        case=_case(),
        gold=_gold(),
        arm="S_DYNAMIC",
        replicate=1,
        manifest=_manifest(),
        repo_root=Path(__file__).parents[1],
        provider=_dynamic_provider,
    )
    assert result["score"]["full_hard_gate"] is True
    assert result["score"]["critical_path_recall"] == 1.0
    assert result["trace"]["stop_reason"] == "answer"
    assert result["trace"]["retrieval_actions"] <= 10


def test_graph_first_direct_handoff_can_finish_before_search(tmp_path: Path) -> None:
    state = FactorialHostState(
        _service(tmp_path), _case(), static=False, guard_enabled=True)
    assert state.dispatch({
        "action": "read_candidate", "path": "docs/Handoff.md",
        "start": 1, "end": 3,
    })["ok"] is True
    expanded = state.dispatch({"action": "expand_candidates"})
    assert "docs/Authority.md" in expanded["result_paths"]
    assert state.dispatch({
        "action": "follow_link", "path": "docs/Handoff.md",
    })["ok"] is True
    for _ in range(2):
        assert state.dispatch({
            "action": "read_candidate", "path": "docs/Authority.md",
            "start": 1, "end": 4,
        })["ok"] is True
    terminal = state.dispatch({"action": "finish", "terminal_action": "answer"})
    assert terminal["ok"] is True
    assert state.stop_reason == "answer"


def test_static_cell_follows_host_owned_recall_first_plan(tmp_path: Path) -> None:
    _require_unix_socket()
    result = run_cell(
        service=_service(tmp_path),
        case=_case(),
        gold=_gold(),
        arm="S_STATIC",
        replicate=1,
        manifest=_manifest(),
        repo_root=Path(__file__).parents[1],
        provider=_static_provider,
    )
    assert result["score"]["full_hard_gate"] is True
    actions = [item["action"] for item in result["trace"]["actions"]]
    assert actions[:3] == ["reformulate_query", "reformulate_query", "expand_candidates"]
    assert actions[-1] == "answer"


def test_subagent_contract_rejects_unstructured_or_conclusive_payload() -> None:
    payload = {
        "contract_version": SUBAGENT_VERSION,
        "candidate_paths": ["docs/Handoff.md"],
        "read_ranges": [],
        "search_trace": [],
        "uncertainty": "none",
        "next_action": "run it",
    }
    with pytest.raises(ContractError, match="C3"):
        validate_subagent_output(payload)


def test_helper_rejects_path_not_observed_by_host(tmp_path: Path) -> None:
    _require_unix_socket()
    def dishonest(subject, socket_path, prompt, schema_name, config, **kwargs):
        del subject, prompt, schema_name, config, kwargs
        _socket_request(socket_path, {
            "action": "search", "query": "zephyr relay continuation"})
        return {
            "payload": {
                "contract_version": SUBAGENT_VERSION,
                "candidate_paths": ["docs/Authority.md", "notes/unseen.md"],
                "read_ranges": [],
                "search_trace": [{
                    "action": "search",
                    "query_or_path": "zephyr relay continuation",
                    "result_paths": ["docs/Authority.md"],
                }],
                "uncertainty": "none",
            },
            "raw": "dishonest",
            "provider_meta": {},
        }

    result = run_helper(
        service=_service(tmp_path), case=_case(), manifest=_manifest(),
        repo_root=Path(__file__).parents[1], provider=dishonest)
    assert result["valid"] is False
    assert result["failure_code"] == "C3"


def _write_design(root: Path) -> Path:
    manifest = _manifest()
    (root / "cases").mkdir(parents=True)
    (root / "gold").mkdir()
    difficulties = sorted(DIFFICULTIES)
    for split, prefix in (("development", "DEV"), ("held_out", "HOLD")):
        for index, case_id in enumerate(manifest["splits"][split]):
            difficulty = difficulties[index]
            case = _case(case_id, difficulty)
            truth = _gold(case_id, absent=difficulty.endswith("no-gold"))
            (root / "cases" / f"{case_id}.json").write_text(
                json.dumps(case), encoding="utf-8")
            (root / "gold" / f"{case_id}.json").write_text(
                json.dumps(truth), encoding="utf-8")
    profile = {"root": str(root / "vault"), "obsidian_enabled": False}
    (root / "vault").mkdir()
    _write(
        root / "vault" / "docs" / "Handoff.md",
        "# Handoff\nProject zephyr relay.\nSee [authority](Authority.md).\n",
    )
    _write(
        root / "vault" / "docs" / "Authority.md",
        "# Authority\nSTATE_READY is current.\nNEXT_RUN_ONE is next.\nSTOP_GREEN ends work.\n",
    )
    for number in range(1, 8):
        _write(
            root / "vault" / "notes" / f"Distractor-{number}.md",
            f"# Zephyr distractor {number}\nrelay archive unrelated {number}\n",
        )
    (root / "profile.json").write_text(json.dumps(profile), encoding="utf-8")
    manifest_path = root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def test_factorial_freeze_detects_case_or_harness_drift(tmp_path: Path) -> None:
    repo = Path(__file__).parents[1]
    manifest_path = _write_design(tmp_path)
    load_cases_and_gold(manifest_path)
    receipt = build_freeze(manifest_path, repo)
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_text(json.dumps(receipt), encoding="utf-8")
    assert verify_freeze(manifest_path, repo, freeze_path)["status"] == "PASS"
    case_path = tmp_path / "cases" / "DEV-01.json"
    case_path.write_text(case_path.read_text() + "\n", encoding="utf-8")
    assert verify_freeze(manifest_path, repo, freeze_path)["status"] == "FAIL"


def _row(case_id: str, arm: str, passed: bool, *, invalid: bool = False) -> dict:
    return {
        "case_id": case_id,
        "arm": arm,
        "replicate": 1,
        "is_absent": False,
        "full_hard_gate": passed,
        "critical_path_recall": float(passed),
        "exact_authority_hit": passed,
        "invalid_run": invalid,
        "false_absence": False,
        "premature_stop": False,
        "retrieval_actions": 4,
        "wall_clock_ms": 1,
    }


def test_screen_gate_requires_two_improvements_and_no_regression() -> None:
    rows = []
    for number in range(1, 9):
        case_id = f"DEV-{number:02d}"
        rows.append(_row(case_id, "S_STATIC", number > 2))
        rows.append(_row(case_id, "S_DYNAMIC", True))
    summary = score_rows(rows, stage="screen")
    assert summary["screen_gate"]["decision"] == "FULL_2X2"
    rows[-1]["full_hard_gate"] = False
    regressed = score_rows(rows, stage="screen")
    assert regressed["screen_gate"]["decision"] == "STATIC_SUBAGENT_ONLY"


def test_codex_usage_is_structured_from_final_turn() -> None:
    raw = "\n".join([
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 10, "cached_input_tokens": 4,
            "output_tokens": 2, "reasoning_output_tokens": 1}}),
        json.dumps({"type": "turn.completed", "usage": {
            "input_tokens": 20, "cached_input_tokens": 8,
            "output_tokens": 3, "reasoning_output_tokens": 2}}),
    ])
    usage = _codex_usage_summary(raw)
    assert usage["input_tokens"] == 20
    assert usage["cached_input_tokens"] == 8
    assert usage["output_tokens"] == 3


def test_screen_stage_runs_exact_matrix_and_writes_summary(tmp_path: Path) -> None:
    _require_unix_socket()
    repo = Path(__file__).parents[1]
    design = tmp_path / "design"
    manifest_path = _write_design(design)
    freeze_path = design / "freeze.json"
    freeze_path.write_text(
        json.dumps(build_freeze(manifest_path, repo)), encoding="utf-8")

    def provider(subject, socket_path, prompt, schema_name, config, **kwargs):
        del subject, schema_name, config, kwargs
        case_id = re.search(r"Public case ID: (\S+)", prompt).group(1)
        arm = re.search(r"arm (S_STATIC|S_DYNAMIC)", prompt).group(1)
        if arm == "S_STATIC":
            searches = 0
            while True:
                step = _socket_request(socket_path, {"action": "status"})["static_next"]
                if step["action"] == "search":
                    query = ("zephyr relay continuation" if searches == 0
                             else "project authority current next stop")
                    searches += 1
                    _socket_request(socket_path, {"action": "search", "query": query})
                elif step["action"] in {"read_candidate", "follow_link"}:
                    _socket_request(socket_path, {
                        "action": step["action"], "path": step["path"],
                        "start": 1, "end": 4})
                elif step["action"] == "expand_candidates":
                    _socket_request(socket_path, {"action": "expand_candidates"})
                else:
                    _socket_request(socket_path, {
                        "action": "finish", "terminal_action": "answer"})
                    break
        else:
            _dynamic_provider(None, socket_path, "", "", {}, **{})
        payload = _answer(case_id, arm)
        return {"payload": payload, "raw": "stage", "provider_meta": {}}

    output = tmp_path / "results"
    summary = _run_stage(
        stage="screen",
        manifest_path=manifest_path,
        freeze_path=freeze_path,
        output_dir=output,
        repo_root=repo,
        provider=provider,
    )
    assert summary["n_runs"] == 16
    assert len(list(output.glob("screen-DEV-*-S_*-r1.json"))) == 16
    assert (output / "screen-summary.json").is_file()

    summary_path = output / "screen-summary.json"
    forged = json.loads(summary_path.read_text())
    forged["n_runs"] = 1
    summary_path.write_text(json.dumps(forged), encoding="utf-8")
    with pytest.raises(DesignError, match="does not match"):
        _run_stage(
            stage="confirm",
            manifest_path=manifest_path,
            freeze_path=freeze_path,
            output_dir=output,
            repo_root=repo,
            provider=lambda *args, **kwargs: pytest.fail("provider must not run"),
        )
