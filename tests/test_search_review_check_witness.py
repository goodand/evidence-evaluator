"""Every review code vault_search can emit must prove it fires AND stays silent.

WHY THIS FILE EXISTS
--------------------
An independent zero-context test (docs/INDEPENDENT_TEST_HAIKU_MCP_20260822.md)
showed that vault_search's aggregated warning -- "Obsidian CLI graph probes
unavailable or failed: N; filesystem fallback used." -- reads as "the CLI is
down" when the CLI was healthy and the N failed probes were simply paths
Obsidian does not index (dot-directories). Two different worlds, one signal:
a warning with no negative witness, which is the vacuous-guard family failure
this project has now hit nineteen recorded times.

The fix is not wording. The probe layer now CLASSIFIES each failure
(NOT_INDEXED / CLI_UNAVAILABLE / CLI_ERROR) and the service emits coded
`review_checks` -- the same contract shape as `.vault-harness`'s exception
checks and vault-backlinks-mcp's review_checks, reused rather than invented.
This registry gives each code one world where it must speak and one where it
must stay silent, mirroring vault-backlinks-mcp/tests/test_guard_witness.py.

THE DECISIVE PAIR is CLI_UNAVAILABLE's negative witness: a world where the CLI
is healthy but the probed path is not indexed must NOT produce
CLI_UNAVAILABLE. That world is the haiku finding, made a permanent regression
guard.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

from evidence_evaluator.retrieval.obsidian import ObsidianCliBackend
from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.service import RetrievalService

SERVICE_SOURCE = (
    Path(__file__).resolve().parent.parent
    / "evidence_evaluator" / "retrieval" / "service.py"
).read_text(encoding="utf-8")


def _codes_in_source() -> set[str]:
    """Literal {"code": "X"} dict entries in service.py, via AST.

    Deliberately the same 12-line parse as vault-backlinks-mcp's
    tests/test_guard_witness.py (fe0b706) and the selftest-harness -- parsing,
    not a regex, so there is no character class to forget to widen and prose
    mentions of a code are not counted as guards. Kept as a small per-repo copy
    because each repo's tests must run standalone; the shape is the canonical
    one, see HARNESS_KNOWHOW.md §B4a.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(SERVICE_SOURCE)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == "code"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                found.add(value.value)
    return found


# --- worlds -----------------------------------------------------------------

def _vault(tmp: Path) -> VaultProfile:
    (tmp / "HANDOFF.md").write_text(
        "# Handoff\n\nfrost resume entry. See [[bridge]].\n", encoding="utf-8")
    (tmp / "bridge.md").write_text(
        "# Bridge\n\nfrost resume continues at [[HANDOFF]].\n", encoding="utf-8")
    return VaultProfile(root=tmp, obsidian_enabled=True)


def _completed(command, code: int, out: str = "", err: str = ""):
    return subprocess.CompletedProcess(command, code, out, err)


def _healthy_runner(command, cwd, timeout):
    if "backlinks" in command:
        return _completed(command, 0, json.dumps([{"file": "bridge.md"}]))
    return _completed(command, 0, "HANDOFF.md\n")


def _not_indexed_runner(command, cwd, timeout):
    """The CLI is alive and answers: this path is not in my index."""
    path = next((p for p in command if p.startswith("path=")), "path=?")
    return _completed(command, 1,
                      f'Error: File "{path[5:]}" not found in vault.')


def _unavailable_runner(command, cwd, timeout):
    """A spawn failure: returncode 127 with a shell-style error whose text
    CONTAINS the substring "not found" ("command not found"). This fixture is
    deliberately the adversarial spelling: a text-first classifier reads it as
    NOT_INDEXED, so it can only classify correctly if the returncode is
    checked before the text -- see
    test_spawn_failure_is_not_misread_as_not_indexed.

    The first version of this fixture used "[Errno 2] No such file or
    directory", which does NOT contain "not found" -- so the order-pinning
    test passed with the classification order inverted. A poison test caught
    that the witness was vacuous; this spelling is the one the poison run
    proved discriminating."""
    return _completed(command, 127, "", "sh: obsidian: command not found")


def _erroring_runner(command, cwd, timeout):
    return _completed(command, 1, "", "ipc handler crashed unexpectedly")


def _search(tmp: Path, runner) -> dict:
    profile = _vault(tmp)
    service = RetrievalService(
        profile, obsidian=ObsidianCliBackend(profile, runner=runner))
    return service.search("frost resume", output_k=2, candidate_pool_k=10,
                          graph_seed_k=2, max_turns=3)


def _codes(result: dict) -> set[str]:
    return {check["code"] for check in result.get("review_checks", [])}


# --- the registry -----------------------------------------------------------

SEARCH_REVIEW_WITNESSES: dict[str, tuple[Callable, Callable, str]] = {
    "PATHS_NOT_INDEXED": (
        lambda tmp: _search(tmp, _not_indexed_runner),
        lambda tmp: _search(tmp, _healthy_runner),
        "probed paths outside Obsidian's index vs every probe answered",
    ),
    "CLI_UNAVAILABLE": (
        lambda tmp: _search(tmp, _unavailable_runner),
        # The haiku finding as a permanent negative witness: a healthy CLI
        # answering "not found" for unindexed paths must NOT be reported as
        # the CLI being down.
        lambda tmp: _search(tmp, _not_indexed_runner),
        "the CLI process failing to answer vs a healthy CLI whose index "
        "simply does not contain the probed paths",
    ),
    "CLI_ERROR": (
        lambda tmp: _search(tmp, _erroring_runner),
        lambda tmp: _search(tmp, _healthy_runner),
        "the CLI answering with an unclassified error vs answering normally",
    ),
}

KNOWN_UNPROVEN: dict[str, str] = {
    # Empty, and the staleness tests below keep it honest in both directions.
    # Do not fabricate a witness to keep it empty -- see
    # vault-backlinks-mcp/tests/test_guard_witness.py for the rule.
}


# --- completeness, both directions -------------------------------------------

def test_every_search_review_code_is_registered():
    in_source = _codes_in_source()
    assert in_source, (
        "the parse found no review codes in service.py at all -- either the "
        "codes have not been implemented yet (this test is written first, "
        "TDD), or the scanner broke. A completeness check over an empty set "
        "passes trivially, so this fails instead."
    )
    missing = in_source - set(SEARCH_REVIEW_WITNESSES) - set(KNOWN_UNPROVEN)
    assert not missing, (
        f"review code(s) emitted by service.py with no registered witness: "
        f"{sorted(missing)}"
    )


def test_the_registry_does_not_claim_codes_that_no_longer_exist():
    stale = set(SEARCH_REVIEW_WITNESSES) - _codes_in_source()
    assert not stale, (
        f"registered witness(es) for code(s) service.py never emits: "
        f"{sorted(stale)}"
    )


def test_known_unproven_entries_are_not_stale():
    in_source = _codes_in_source()
    vanished = sorted(c for c in KNOWN_UNPROVEN if c not in in_source)
    assert not vanished, (
        f"KNOWN_UNPROVEN names code(s) absent from service.py -- delete them; "
        f"a future code reusing the name would inherit the exemption: {vanished}"
    )
    obsolete = sorted(c for c in KNOWN_UNPROVEN if c in SEARCH_REVIEW_WITNESSES)
    assert not obsolete, (
        f"these code(s) now have a witness; the exemption is obsolete: {obsolete}"
    )


@pytest.mark.parametrize("bogus,expected", [
    ("A_CODE_NEVER_EMITTED_ANYWHERE", "absent from service.py"),
    ("PATHS_NOT_INDEXED", "obsolete"),
])
def test_the_staleness_check_itself_fires_on_a_bogus_entry(monkeypatch, bogus,
                                                           expected):
    """The exemption list is a checker, so it gets its own negative witness --
    both failure directions, because a check that catches one is half a check."""
    monkeypatch.setitem(KNOWN_UNPROVEN, bogus, "injected by a negative witness")
    with pytest.raises(AssertionError, match=expected):
        test_known_unproven_entries_are_not_stale()


# --- the witnesses ------------------------------------------------------------

@pytest.mark.parametrize("code", sorted(SEARCH_REVIEW_WITNESSES))
def test_code_fires_on_its_positive_witness(code, tmp_path):
    positive, _, why = SEARCH_REVIEW_WITNESSES[code]
    result = positive(tmp_path)
    assert code in _codes(result), (
        f"{code} did not fire on the world it exists to detect ({why}). "
        f"review_checks={result.get('review_checks')}"
    )


@pytest.mark.parametrize("code", sorted(SEARCH_REVIEW_WITNESSES))
def test_code_stays_silent_on_its_negative_witness(code, tmp_path):
    _, negative, why = SEARCH_REVIEW_WITNESSES[code]
    result = negative(tmp_path)
    assert code not in _codes(result), (
        f"{code} fired on a world where it must stay silent ({why}). This is "
        f"the sensitivity-without-specificity failure that made the original "
        f"warning unreadable. review_checks={result.get('review_checks')}"
    )


# --- properties the codes must carry ------------------------------------------

def test_spawn_failure_is_not_misread_as_not_indexed(tmp_path):
    """The classification-order trap, pinned. A spawn failure's OS error text
    contains "No such file or directory", which a naive text match reads as
    NOT_INDEXED -- inverting the haiku finding instead of fixing it. The
    returncode/unavailability checks must run first."""
    result = _search(tmp_path, _unavailable_runner)
    assert "CLI_UNAVAILABLE" in _codes(result)
    assert "PATHS_NOT_INDEXED" not in _codes(result), (
        "a dead CLI was classified as 'paths not indexed' -- the misreading "
        "this change exists to prevent, in the opposite direction"
    )


def test_every_emitted_check_carries_a_required_action(tmp_path):
    """review_required with no instruction is a warning, not a contract --
    same rule as the canonical harness and the selftest harness."""
    for code, (positive, _, _) in SEARCH_REVIEW_WITNESSES.items():
        world = tmp_path / code
        world.mkdir()
        result = positive(world)
        check = next(c for c in result["review_checks"] if c["code"] == code)
        assert len(check.get("required_action", "")) >= 40, (
            f"{code} has a missing or stub required_action"
        )
        assert check.get("count", 0) >= 1


def test_failure_worlds_label_filesystem_fallback(tmp_path):
    """Whenever any probe failed, the graph answer is partly filesystem-sourced
    and fallback_used must say so; the healthy world must not claim a fallback."""
    for runner in (_not_indexed_runner, _unavailable_runner, _erroring_runner):
        sub = tmp_path / runner.__name__
        sub.mkdir()
        assert _search(sub, runner)["fallback_used"] == "filesystem"
    healthy = tmp_path / "healthy"
    healthy.mkdir()
    assert _search(healthy, _healthy_runner)["fallback_used"] is None
