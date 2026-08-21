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


def test_obsidian_unavailable_falls_back_but_is_clearly_labeled(vault, monkeypatch):
    """2026-08-15: a live CLI failure no longer means an outright failure --
    it now falls back to evidence-evaluator's filesystem scan (default on).
    'Not swallowed' still holds in the sense that matters: the caller is
    NEVER told this is a live answer. `backend_used` says exactly which path
    answered, and a FILESYSTEM_FALLBACK_USED review_check names the tradeoff
    (broader, lower-precision) every time this path fires."""
    from obsidian_backend import ObsidianUnavailable

    def raise_unavailable(root, name, path):
        raise ObsidianUnavailable("obsidian CLI is not on PATH")
    monkeypatch.setattr(contracts, "fetch_backlinks", raise_unavailable)

    # Spy on the fallback itself, not just its side effects. An adversarial
    # review (2026-08-15) showed the earlier version of this test passed even
    # when the fallback call was replaced by a hardcoded empty list -- it
    # asserted only on the shape of the result, so "the fallback ran" and
    # "something produced a fallback-shaped result" were indistinguishable.
    calls = []
    # The real fallback comes from its home module, NOT off `contracts`, and
    # the switch is pinned on. `contracts` reads the environment at IMPORT
    # time and binds `filesystem_fallback_backlinks` to None when the fallback
    # is off, so reading it from there made this test inherit whatever state
    # the ambient environment -- or a previously-run test's reload -- left
    # behind. Found by the harness's within-file shuffle: this test PASSED in
    # definition order and FAILED under pinned seeds 2-4, where the
    # env-parsing test's reload ran first. Same fix as the F2 witness.
    from obsidian_backend_evidence import filesystem_fallback_backlinks as real_fallback

    def spy(vault_root, path):
        calls.append((vault_root, path))
        return real_fallback(vault_root, path)
    monkeypatch.setattr(contracts, "FILESYSTEM_FALLBACK_ENABLED", True)
    monkeypatch.setattr(contracts, "filesystem_fallback_backlinks", spy)

    # Give the fixture a REAL incoming link. A second adversarial review
    # (2026-08-16) showed the spy alone was still not enough: this vault has
    # no wikilinks, so the genuine fallback returned [] -- indistinguishable
    # from a mutation that returns a hardcoded [] without scanning anything,
    # because `[] is not None` passes either way. Now the scan has something
    # to find, and the assertion is on the found value.
    (vault["t1"].root / "docs" / "source.md").write_text(
        "see [[target]]", encoding="utf-8")

    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert calls, "the filesystem fallback was never actually called"
    assert calls[0][1] == "target.md"
    assert result["backend_used"] == "filesystem_fallback"
    assert result["backlinks"] == [{"source_path": "docs/source.md", "link_count": 1}], (
        "the fallback must return the link it actually scanned, not an empty list"
    )
    assert result["total"] == 1
    assert result["error"] is None
    assert result["review_required"] is True
    codes = {c["code"] for c in result["review_checks"]}
    assert "FILESYSTEM_FALLBACK_USED" in codes


def test_a_crashing_filesystem_fallback_still_returns_a_structured_error(
    vault, monkeypatch
):
    """Adversarial review 2026-08-15 (blocker): the fallback call was not
    guarded by its own try/except, so an OSError/ProfileError from it (vault
    root deleted or unreadable between registry load and this call) escaped
    `query_backlinks()` as a raw exception -- violating this module's
    contract that every caller-facing failure becomes a structured result.
    A fallback that crashes is worse than the honest failure it replaced."""
    from obsidian_backend import ObsidianUnavailable

    def raise_unavailable(root, name, path):
        raise ObsidianUnavailable("obsidian CLI is not on PATH")

    def exploding_fallback(vault_root, path):
        raise OSError("vault root vanished")

    monkeypatch.setattr(contracts, "fetch_backlinks", raise_unavailable)
    # Pinned on for the same reason as the spy test above: the world this test
    # describes requires the fallback path to be taken, so the test builds
    # that world instead of inheriting it from import-time configuration.
    monkeypatch.setattr(contracts, "FILESYSTEM_FALLBACK_ENABLED", True)
    monkeypatch.setattr(contracts, "filesystem_fallback_backlinks", exploding_fallback)

    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert result["backend_used"] == "none"
    assert result["backlinks"] is None
    assert "obsidian CLI is not on PATH" in result["error"]
    assert "vault root vanished" in result["error"]


def test_unrecognized_fallback_env_values_do_not_silently_disable_it(monkeypatch):
    """Adversarial review 2026-08-15: the switch used a blocklist of three
    exact strings, so "disabled"/"No"/"off" read as ENABLED -- the opposite
    of what someone typing them intends. Recognized off-spellings must turn
    it off; anything unrecognized still defaults to on."""
    import importlib
    import os
    # This test reloads `contracts`, and monkeypatch cannot undo a reload --
    # the teardown restores os.environ but the MODULE stays configured by
    # whatever the last reload saw. The original cleanup did
    # `delenv` + reload, which reconfigured the module to "fallback on"
    # regardless of the ambient environment, and that leak masked the F2
    # witness's own environment dependence for the rest of the session
    # (docs/PRIOR_ART_ORDER_DEPENDENCE_20260818.md). The finally below
    # restores the ORIGINAL value -- present or absent -- and reloads once
    # more, so the module leaves this test in the state it entered it.
    original = os.environ.get("VAULT_BACKLINKS_FILESYSTEM_FALLBACK")
    # Uppercase spellings included deliberately: a follow-up review
    # (2026-08-16) found the comparison was case-sensitive, so "FALSE"/"OFF"/
    # "NO" fell through and ENABLED the fallback an operator was disabling.
    try:
        for value, expected in (("0", False), ("false", False), ("False", False),
                                ("FALSE", False), ("no", False), ("NO", False),
                                ("off", False), ("OFF", False),
                                ("disabled", False), ("DISABLED", False),
                                (" 0 ", False), ("1", True), ("true", True),
                                ("", True)):
            monkeypatch.setenv("VAULT_BACKLINKS_FILESYSTEM_FALLBACK", value)
            reloaded = importlib.reload(contracts)
            assert reloaded.FILESYSTEM_FALLBACK_ENABLED is expected, (
                f"{value!r} should map to enabled={expected}"
            )
    finally:
        if original is None:
            os.environ.pop("VAULT_BACKLINKS_FILESYSTEM_FALLBACK", None)
        else:
            os.environ["VAULT_BACKLINKS_FILESYSTEM_FALLBACK"] = original
        importlib.reload(contracts)


def test_obsidian_unavailable_is_an_honest_failure_when_fallback_is_off(
    vault, monkeypatch
):
    """The pre-2026-08-15 contract is still reachable: with the fallback
    switched off, a live failure must not be silently answered from
    anywhere else."""
    from obsidian_backend import ObsidianUnavailable

    def raise_unavailable(root, name, path):
        raise ObsidianUnavailable("obsidian CLI is not on PATH")
    monkeypatch.setattr(contracts, "fetch_backlinks", raise_unavailable)
    monkeypatch.setattr(contracts, "FILESYSTEM_FALLBACK_ENABLED", False)

    # Assert the fallback was not merely ineffective but never REACHED.
    # Adversarial review 2026-08-16: inferring "it didn't run" from
    # backend_used/error alone cannot tell "the switch stopped it" from "it
    # ran and happened to produce nothing usable" -- and only the first is
    # the contract being tested here.
    calls = []

    def must_not_run(vault_root, path):
        calls.append((vault_root, path))
        return ["docs/source.md"]
    monkeypatch.setattr(contracts, "filesystem_fallback_backlinks", must_not_run)

    # Give the vault a real link, so a fallback that DID run would visibly
    # change the result rather than coincidentally matching the failure shape.
    (vault["t1"].root / "docs" / "source.md").write_text(
        "see [[target]]", encoding="utf-8")

    result = contracts.query_backlinks("t1", "target.md", registry=vault)
    assert calls == [], "the fallback ran even though it was switched off"
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
