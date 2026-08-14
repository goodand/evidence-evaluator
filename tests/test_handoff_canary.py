from __future__ import annotations

import json
from pathlib import Path

import pytest

from evidence_evaluator.handoff_canary import (
    CASE_VERSION,
    GOLD_VERSION,
    assess_canary,
    run_canary,
)
from evidence_evaluator.providers import (
    CodexMcpServerSpec,
    ProviderError,
    _codex_event_summary,
    codex_external_mcp_command,
    validate_against_schema,
)
from evidence_evaluator.retrieval.mcp_server import McpAuditLog


HANDOFF = "notes/handoff.md"
AUTHORITY = "notes/authority.md"


def _case() -> dict:
    return {
        "contract_version": CASE_VERSION,
        "id": "C01",
        "project_id": "P01",
        "question": "recover P01",
    }


def _gold() -> dict:
    return {
        "contract_version": GOLD_VERSION,
        "case_id": "C01",
        "handoff_path": HANDOFF,
        "authority_paths": [AUTHORITY],
        "required_read_paths": [HANDOFF, AUTHORITY],
        "state_code": "READY",
        "next_action_code": "RUN_ONE",
        "stop_condition_codes": ["STOP_ONE"],
    }


def _citation(path: str) -> dict:
    return {"path": path, "line_start": 1, "line_end": 2}


def _payload(*, citation_path: str = AUTHORITY) -> dict:
    claim = {"text": "supported", "citations": [_citation(citation_path)]}
    return {
        "answer": "ready",
        "state_code": "READY",
        "current_state": claim,
        "next_action_code": "RUN_ONE",
        "next_action": claim,
        "stop_condition_codes": ["STOP_ONE"],
        "stop_conditions": [claim],
        "uncertainty": "none",
    }


def _records() -> list[dict]:
    return [
        {
            "tool": "vault_search",
            "outcome": "ok",
            "result": {"retrieved_paths": [HANDOFF, AUTHORITY]},
        },
        {
            "tool": "vault_read",
            "outcome": "ok",
            "result": {
                "canonical_path": HANDOFF,
                "line_start": 1,
                "line_end": 20,
                "content_sha256": "a" * 64,
            },
        },
        {
            "tool": "vault_read",
            "outcome": "ok",
            "result": {
                "canonical_path": AUTHORITY,
                "line_start": 1,
                "line_end": 20,
                "content_sha256": "b" * 64,
            },
        },
    ]


def _meta() -> dict:
    return {"tool_event_summary": {"forbidden": []}}


def test_canary_accepts_only_observed_search_reads_and_supported_claims() -> None:
    result = assess_canary(
        _case(), _gold(), _payload(), _records(), _meta(), max_calls=6
    )
    assert result["accepted"] is True
    assert result["runtime"]["valid"] is True
    assert result["retrieval"]["critical_path_recall"] == 1.0
    assert result["reconstruction"]["citations_supported_by_actual_reads"] is True


def test_navigation_must_be_discovered_but_need_not_be_read() -> None:
    gold = _gold()
    gold["navigation_paths"] = ["notes/entry.md"]
    records = _records()
    records[0]["result"]["retrieved_paths"].append("notes/entry.md")
    result = assess_canary(_case(), gold, _payload(), records, _meta(), max_calls=6)
    assert result["accepted"] is True
    assert "notes/entry.md" not in result["retrieval"]["read_paths"]
    assert result["retrieval"]["navigation_discovery_recall"] == 1.0

    records[0]["result"]["retrieved_paths"].remove("notes/entry.md")
    missed = assess_canary(_case(), gold, _payload(), records, _meta(), max_calls=6)
    assert missed["accepted"] is False
    assert missed["retrieval"]["navigation_discovery_recall"] == 0.0


def test_reading_authority_is_not_enough_when_claims_cite_only_navigation() -> None:
    payload = _payload(citation_path=HANDOFF)
    result = assess_canary(
        _case(), _gold(), payload, _records(), _meta(), max_calls=6
    )
    assert result["runtime"]["valid"] is True
    assert result["retrieval"]["exact_authority_hit"] is True
    assert result["reconstruction"]["citations_supported_by_actual_reads"] is True
    assert result["reconstruction"][
        "authority_citation_present_for_every_claim"
    ] is False
    assert result["accepted"] is False


def test_committed_output_schema_parses_and_enforces_the_subject_payload() -> None:
    schema = json.loads(
        (Path(__file__).parents[1] / "examples" / "handoff-canary-output.schema.json")
        .read_text(encoding="utf-8")
    )
    validate_against_schema(_payload(), schema)
    malformed = _payload()
    del malformed["next_action"]
    with pytest.raises(ProviderError, match="missing required"):
        validate_against_schema(malformed, schema)


@pytest.mark.parametrize(
    ("records", "payload", "field"),
    [
        ([], _payload(), ("runtime", "valid")),
        (_records()[:1], _payload(), ("runtime", "valid")),
        (_records()[:2], _payload(), ("retrieval", "critical_path_recall")),
        (_records(), _payload(citation_path="notes/unread.md"),
         ("reconstruction", "citations_supported_by_actual_reads")),
    ],
)
def test_canary_negative_paths_do_not_pass(
    records: list[dict], payload: dict, field: tuple[str, str]
) -> None:
    result = assess_canary(_case(), _gold(), payload, records, _meta(), max_calls=6)
    assert result["accepted"] is False
    observed = result[field[0]][field[1]]
    assert observed is False or observed < 1.0


def test_canary_rejects_native_or_unrelated_tool_events() -> None:
    native = json.dumps({"item": {"type": "command_execution", "name": "shell"}})
    with pytest.raises(ProviderError, match="forbidden"):
        _codex_event_summary(native, frozenset({"vault_search"}))

    unrelated = json.dumps(
        {"item": {"type": "mcp_tool_call", "tool": "other_tool"}}
    )
    with pytest.raises(ProviderError, match="other_tool"):
        _codex_event_summary(unrelated, frozenset({"vault_search"}))


def test_codex_command_exposes_only_the_requested_mcp(tmp_path: Path) -> None:
    server = CodexMcpServerSpec(
        name="evidence_vault",
        command="/tmp/server",
        args=("--stdio",),
        env={"TOKEN": "not-a-real-secret"},
        enabled_tools=("vault_search", "vault_read", "vault_backlinks"),
    )
    command = codex_external_mcp_command(
        "codex",
        tmp_path,
        tmp_path / "schema.json",
        tmp_path / "output.json",
        {"model": "test", "reasoning_effort": "low"},
        server,
    )
    joined = " ".join(command)
    assert "mcp_servers.evidence_vault.enabled_tools" in joined
    assert "vault_search" in joined
    assert "handoff_action" not in joined
    assert 'TOKEN = "not-a-real-secret"' in joined
    assert "--ignore-user-config" in command
    assert "--ignore-rules" in command
    assert "shell_tool" in command


def test_mcp_call_budget_fails_closed() -> None:
    audit = McpAuditLog(None, max_calls=1)
    audit.begin("vault_search", {})
    with pytest.raises(ValueError, match="budget exhausted"):
        audit.begin("vault_read", {})


def _write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_run_canary_scripted_e2e_preserves_audit_and_provenance(tmp_path: Path) -> None:
    case_path, gold_path = tmp_path / "case.json", tmp_path / "gold.json"
    profile_path, schema_path = tmp_path / "profile.json", tmp_path / "schema.json"
    output_path = tmp_path / "results" / "run.json"
    _write_json(case_path, _case())
    _write_json(gold_path, _gold())
    _write_json(profile_path, {"root": str(tmp_path)})
    schema_path.write_text(
        (Path(__file__).parents[1] / "examples" / "handoff-canary-output.schema.json")
        .read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    def scripted(subject, prompt, schema, config, *, server, run_name):
        del subject, prompt, schema, config, run_name
        audit_path = Path(server.env["EVIDENCE_MCP_AUDIT_LOG"])
        audit_path.write_text(
            "\n".join(json.dumps(record) for record in _records()) + "\n",
            encoding="utf-8",
        )
        return {
            "payload": _payload(),
            "raw": "scripted raw",
            "provider_meta": {"tool_event_summary": {"forbidden": []}},
        }

    result = run_canary(
        profile_path=profile_path,
        case_path=case_path,
        gold_path=gold_path,
        schema_path=schema_path,
        model="explicit-test-model",
        output_path=output_path,
        provider=scripted,
    )
    assert result["accepted"] is True
    assert output_path.is_file()
    assert output_path.with_suffix(".mcp-audit.jsonl").is_file()
    assert output_path.with_suffix(".provider.jsonl").read_text() == "scripted raw"
    assert len(result["provenance"]["mcp_audit_sha256"]) == 64


def test_run_canary_timeout_is_invalid_not_retrieval_zero(tmp_path: Path) -> None:
    case_path, gold_path = tmp_path / "case.json", tmp_path / "gold.json"
    profile_path, schema_path = tmp_path / "profile.json", tmp_path / "schema.json"
    _write_json(case_path, _case())
    _write_json(gold_path, _gold())
    _write_json(profile_path, {"root": str(tmp_path)})
    schema_path.write_text("{}", encoding="utf-8")

    def timeout(*args, **kwargs):
        raise ProviderError("timed out")

    result = run_canary(
        profile_path=profile_path,
        case_path=case_path,
        gold_path=gold_path,
        schema_path=schema_path,
        model="explicit-test-model",
        output_path=tmp_path / "timeout.json",
        provider=timeout,
    )
    assert result["invalid_run"] is True
    assert result["retrieval"] is None
