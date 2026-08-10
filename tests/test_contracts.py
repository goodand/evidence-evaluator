"""Exercises `contracts.query_backlinks()` end to end with a fake
`graph_for_candidate` -- no real Obsidian CLI or `.vault-harness/` needed.
The fake stands in for the *external* IPC call only; every check downstream
of it (registry lookup, path safety, the vault-root cross-check, result
shaping) is this package's own code and runs for real.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

import contracts  # noqa: E402
from registry import VaultEntry  # noqa: E402


@pytest.fixture()
def vault(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "target.md").write_text("t", encoding="utf-8")
    (tmp_path / "docs" / "source.md").write_text("s", encoding="utf-8")
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "gold.json").write_text("{}", encoding="utf-8")
    return {"t1": VaultEntry(vault_id="t1", root=tmp_path, obsidian_vault_name="T1")}


def _fake_graph(backlinks_result):
    def graph_for_candidate(vault_root, vault_name, path):
        return {"backlinks": backlinks_result, "outgoing_links": [], "tags": []}, []
    return graph_for_candidate


def test_real_backlink_is_returned(vault, monkeypatch):
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: [{"file": "docs/source.md", "count": "2"}])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert result["error"] is None
    assert result["backend_used"] == "live"
    assert result["backlinks"] == [{"source_path": "docs/source.md", "link_count": 2}]
    assert result["review_required"] is False


def test_out_of_scope_result_is_dropped_and_flagged(vault, monkeypatch):
    """The load-bearing safety behaviour: a CLI-returned path that does not
    exist under the vault_id's own root (e.g. the CLI silently answered from
    a different, wrong vault -- measured 2026-08-08, see
    obsidian_backend.py) must never be trusted or silently kept."""
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: [{"file": "not/in/this/vault.md", "count": "1"}])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert result["backlinks"] == []
    assert result["dropped_out_of_scope"] == 1
    assert result["review_required"] is True
    codes = [c["code"] for c in result["review_checks"]]
    assert "ALL_RESULTS_OUT_OF_SCOPE" in codes


def test_forbidden_target_path_is_refused_before_any_cli_call(vault, monkeypatch):
    calls = []
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: calls.append(1) or [])
    result = contracts.query_backlinks("t1", "hidden_gold/gold.json", registry=vault)
    assert result["error"] is not None
    assert result["backend_used"] == "none"
    assert calls == [], "must refuse before ever calling the live backend"


def test_raw_string_result_from_non_json_cli_fallback_does_not_crash(vault, monkeypatch):
    """Regression (found 2026-08-08 querying a real vault, not synthetic):
    graph_for_candidate()'s own JSON parse falls back to a list of raw
    strings when the CLI's output for a call wasn't valid JSON. A bare
    'AttributeError: str has no attribute get' would otherwise silently turn
    a real query into a crash instead of a reported result."""
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: ["docs/source.md"])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert result["error"] is None
    assert result["backlinks"] == [{"source_path": "docs/source.md", "link_count": 1}]


def test_forbidden_source_in_cli_result_is_dropped(vault, monkeypatch):
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: [
                            {"file": "docs/source.md", "count": "1"},
                            {"file": "hidden_gold/gold.json", "count": "1"},
                        ])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    sources = [b["source_path"] for b in result["backlinks"]]
    assert "hidden_gold/gold.json" not in sources
    assert "docs/source.md" in sources


def test_unregistered_vault_id_is_refused(vault, monkeypatch):
    calls = []
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: calls.append(1) or [])
    result = contracts.query_backlinks("no-such-vault", "target.md", registry=vault)
    assert result["error"] is not None
    assert result["backend_used"] == "none"
    assert calls == []


def test_path_traversal_is_refused(vault, monkeypatch):
    calls = []
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: calls.append(1) or [])
    result = contracts.query_backlinks("t1", "../../../../etc/hosts", registry=vault)
    assert result["error"] is not None
    assert calls == []


def test_target_path_not_on_disk_is_refused_before_cli_call(vault, monkeypatch):
    calls = []
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: calls.append(1) or [])
    result = contracts.query_backlinks("t1", "does/not/exist.md", registry=vault)
    assert result["error"] is not None
    assert calls == []


def test_obsidian_unavailable_is_reported_not_swallowed(vault, monkeypatch):
    from obsidian_backend import ObsidianUnavailable

    def raise_unavailable(root, name, path):
        raise ObsidianUnavailable("obsidian CLI is not on PATH")
    monkeypatch.setattr(contracts, "fetch_backlinks", raise_unavailable)
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert result["backend_used"] == "none"
    assert result["backlinks"] is None
    assert "obsidian CLI is not on PATH" in result["error"]


def test_max_results_truncation_is_flagged(vault, monkeypatch):
    many = [{"file": "docs/source.md", "count": "1"}] * 5
    monkeypatch.setattr(contracts, "fetch_backlinks", lambda root, name, path: many)
    result = contracts.query_backlinks("t1", "target.md", max_results=2, registry=vault)
    # Regression (2026-08-09, independent review finding #3): `total` used to
    # be computed AFTER truncation (`len(kept[:max_results])`), so 5 real
    # results with max_results=2 reported total=2 -- indistinguishable from
    # "there really are only 2". `total` is the real pre-truncation count;
    # `returned_count` is what this call actually handed back.
    assert result["total"] == 5
    assert result["returned_count"] == 2
    assert len(result["backlinks"]) == 2
    codes = [c["code"] for c in result["review_checks"]]
    assert "TRUNCATED" in codes


def test_max_results_zero_is_rejected(vault):
    """Regression (finding #3): max_results was never validated, so 0 or a
    negative value fell through to Python slice semantics instead of being
    refused."""
    result = contracts.query_backlinks("t1", "target.md", max_results=0, registry=vault)
    assert result["error"] is not None
    assert result["backend_used"] == "none"


def test_max_results_negative_is_rejected(vault, monkeypatch):
    """max_results=-1 used to silently return `kept[:-1]` ('all but the
    last item') instead of an error -- a caller could not distinguish that
    from a real, deliberate result."""
    calls = []
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda root, name, path: calls.append(1) or [])
    result = contracts.query_backlinks("t1", "target.md", max_results=-1, registry=vault)
    assert result["error"] is not None
    assert calls == [], "must fail before ever calling the live backend"


def test_max_results_above_upper_bound_is_rejected(vault):
    result = contracts.query_backlinks(
        "t1", "target.md", max_results=contracts.MAX_RESULTS_UPPER_BOUND + 1, registry=vault)
    assert result["error"] is not None


def test_forbidden_error_message_names_actual_segments_not_evaluation(vault):
    """Regression (2026-08-09, independent review finding #7): the error
    message used to claim 'evaluation/gold data is never queried', but the
    actual forbidden-segment list is only hidden_gold/.git/node_modules --
    retrieval-evaluation documents are a separate, unenforced concept here
    (see docs/feedback/vault_harness_reuse_contract_questions_20260809.md Q4:
    the two policies are intentionally not merged). The message must not
    claim more than the code enforces."""
    result = contracts.query_backlinks("t1", "hidden_gold/gold.json", registry=vault)
    assert result["error"] is not None
    assert "evaluation" not in result["error"].lower()
    assert "hidden_gold" in result["error"]


def test_evaluation_named_document_is_not_blocked_by_this_server(vault, monkeypatch):
    """The flip side of the above: a path that only LOOKS like an evaluation
    report (by the harness's is_evaluation_document naming convention) is not
    a security concept here and must be queryable like any other document."""
    (Path(vault["t1"].root) / "retrieval-evaluation-2026-08-09.md").write_text(
        "x", encoding="utf-8")
    monkeypatch.setattr(contracts, "fetch_backlinks", lambda root, name, path: [])
    result = contracts.query_backlinks(
        "t1", "retrieval-evaluation-2026-08-09.md", registry=vault)
    assert result["error"] is None
    assert result["backend_used"] == "live"


# --- regressions from the 2026-08-09 adversarial review -------------------
# Unit-level guards are not enough here: every one of these was a WIRING
# failure -- the check existed but the pipeline did not apply it (or applied
# a weaker variant). These drive query_backlinks() end to end.

def test_symlink_alias_to_forbidden_dir_never_reaches_the_backend(tmp_path, monkeypatch):
    """`alias -> hidden_gold` cleared the literal forbidden check AND
    exists_under_root, so query_backlinks() called the external CLI with a
    gold path. Reproduced live before the fix."""
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "gold.json").write_text("{}", encoding="utf-8")
    (tmp_path / "alias").symlink_to(tmp_path / "hidden_gold")
    reg = {"t1": VaultEntry(vault_id="t1", root=tmp_path.resolve(),
                            obsidian_vault_name="T1")}
    calls = []
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda *a, **k: calls.append(a) or [])

    result = contracts.query_backlinks("t1", "alias/gold.json", registry=reg)
    assert result["error"] is not None
    assert result["backend_used"] == "none"
    assert calls == [], "must refuse before ever calling the live backend"


def test_collision_message_never_discloses_a_forbidden_path(tmp_path, monkeypatch):
    """BASENAME_COLLISION's required_action named `hidden_gold/target.md`
    verbatim -- leaking the existence and path of a gold file through the one
    code path that wasn't gated by is_forbidden."""
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "target.md").write_text("gold", encoding="utf-8")
    (tmp_path / "target.md").write_text("real", encoding="utf-8")
    reg = {"t1": VaultEntry(vault_id="t1", root=tmp_path.resolve(),
                            obsidian_vault_name="T1")}
    monkeypatch.setattr(contracts, "fetch_backlinks", lambda *a, **k: [])

    result = contracts.query_backlinks("t1", "target.md", registry=reg)
    blob = json.dumps(result, ensure_ascii=False)
    assert "hidden_gold" not in blob, f"forbidden path leaked: {blob}"


def test_drop_reasons_are_not_all_reported_as_vault_mismatch(vault, monkeypatch):
    """A malformed CLI entry (never reaching the vault-root check) still
    produced ALL_RESULTS_OUT_OF_SCOPE claiming the Obsidian app's active
    vault was wrong -- sending the reader after the wrong cause."""
    monkeypatch.setattr(contracts, "fetch_backlinks",
                        lambda *a, **k: [{"file": 12345, "count": "1"}])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)

    codes = [c["code"] for c in result["review_checks"]]
    assert "ALL_RESULTS_OUT_OF_SCOPE" not in codes, \
        "nothing failed the vault-root check; must not blame vault scope"
    assert "ALL_RESULTS_FILTERED" in codes
    assert result["dropped_out_of_scope"] == 0
    assert result["dropped_by_reason"]["malformed"] == 1


# --- regressions from the 2026-08-10 independent review round 2 -----------

def test_malformed_registry_is_a_structured_error_not_an_escaped_exception(tmp_path, monkeypatch):
    """Finding #1: `load_registry()` used to be called OUTSIDE the
    try/except RegistryError block, so a malformed registry file crashed
    query_backlinks() itself with an uncaught RegistryError instead of the
    structured backend_used="none" result every other failure mode gets."""
    import json
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps({
        "contract_version": "vault-registry-v1",
        "vaults": {"bad": "not-an-object"},
    }), encoding="utf-8")
    monkeypatch.setenv("VAULT_BACKLINKS_REGISTRY", str(registry_path))
    result = contracts.query_backlinks("bad", "target.md")  # registry=None -> load_registry()
    assert result["error"] is not None
    assert result["backend_used"] == "none"


def test_contract_version_is_v2_after_the_total_semantics_change(vault):
    """Finding #2: `total`'s meaning changed (pre- vs post-truncation) in
    the previous fix round without bumping CONTRACT_VERSION -- a breaking,
    undetectable-by-version change for any pinned consumer."""
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert result["contract_version"] == "vault-backlinks-result-v2"
    assert result["contract_version"] != "vault-backlinks-result-v1"


def test_path_ambiguous_across_registered_vaults_is_flagged(tmp_path, monkeypatch):
    """Finding #3 (fundamental limitation, not fully closable): if the
    queried path also exists under another registered vault, this tool
    cannot prove which vault the CLI actually answered from. It must not
    stay silent about that specific, checkable condition."""
    vault_a_root = tmp_path / "vault_a"
    vault_b_root = tmp_path / "vault_b"
    vault_a_root.mkdir()
    vault_b_root.mkdir()
    (vault_a_root / "target.md").write_text("a", encoding="utf-8")
    (vault_b_root / "target.md").write_text("b", encoding="utf-8")
    registry = {
        "a": VaultEntry(vault_id="a", root=vault_a_root, obsidian_vault_name="A"),
        "b": VaultEntry(vault_id="b", root=vault_b_root, obsidian_vault_name="B"),
    }
    monkeypatch.setattr(contracts, "fetch_backlinks", lambda root, name, path: [])
    result = contracts.query_backlinks("a", "target.md", registry=registry)
    codes = [c["code"] for c in result["review_checks"]]
    assert "AMBIGUOUS_ACROSS_REGISTERED_VAULTS" in codes


def test_active_vault_mismatch_downgrades_confidence_explicitly(vault, monkeypatch):
    monkeypatch.setattr(contracts, "confirm_active_vault", lambda vault_root: "mismatch")
    monkeypatch.setattr(contracts, "fetch_backlinks", lambda root, name, path: [])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    codes = [c["code"] for c in result["review_checks"]]
    assert "ACTIVE_VAULT_MISMATCH" in codes


def test_active_vault_unknown_is_reported_not_assumed_confirmed(vault, monkeypatch):
    """The review session's explicit guidance: on CLI failure, report
    'unknown', never guess 'confirmed'."""
    monkeypatch.setattr(contracts, "confirm_active_vault", lambda vault_root: "unknown")
    monkeypatch.setattr(contracts, "fetch_backlinks", lambda root, name, path: [])
    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    codes = [c["code"] for c in result["review_checks"]]
    assert "ACTIVE_VAULT_UNKNOWN" in codes
