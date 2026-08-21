"""Every guard must prove it can both fire and stay silent.

WHY THIS FILE EXISTS
---------------------
The recurring failure in this project (17 recorded instances) is that adding
a guard and checking that a guard fires are different facts, and only the
first one gets done. Two of those instances were guards that COULD NOT fire
at all:

  * a `severity="blocking"` check whose condition required "no authority
    documents present", in a system whose pool-refill feature always supplies
    some -- structurally unreachable, never once fired.
  * sandbox probes that ran `/bin/cat` against a DIRECTORY, which fails
    regardless of sandbox rules, so they reported "blocked" under a profile
    with zero deny rules.

Neither was caught by tests passing, by coverage, or by review. Both would
have been caught here, because a guard with no positive witness cannot be
registered, and a guard with no negative witness cannot be distinguished
from one that always fires.

THE REGISTRY ITSELF CAN GO VACUOUS
-----------------------------------
If a new guard is added to `contracts.py` and nobody adds it here, this file
silently stops covering it -- the same "a gate hides a gate" pattern the
project has already hit twice. `test_every_guard_in_the_source_is_registered`
exists to make that impossible: it parses the guard codes straight out of
`contracts.py` and fails on any code this registry does not know about.
That test is the reason the rest of this file cannot quietly decay.
"""
from __future__ import annotations

import importlib
import os
import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

import contracts  # noqa: E402
from registry import VaultEntry  # noqa: E402
from obsidian_backend import ObsidianUnavailable  # noqa: E402
# Imported directly, NOT read off `contracts`. `contracts` binds this name to
# None when VAULT_BACKLINKS_FILESYSTEM_FALLBACK is off at import time, so
# reading it from there would make these witnesses depend on the ambient
# environment. See `_query` and
# `test_the_fallback_witness_does_not_depend_on_import_time_configuration`.
from obsidian_backend_evidence import (  # noqa: E402
    filesystem_fallback_backlinks as _real_filesystem_fallback,
)


CONTRACTS_SOURCE = (PKG / "contracts.py").read_text(encoding="utf-8")


def _codes_in_source() -> set[str]:
    """Guard codes as they actually appear in the module under test.

    AST, not a regex. This follows the canonical scanner in this workspace --
    `concept-gate-taxonomy/test_guard_negative_coverage.py`, documented in
    `concept-gate-codex-mcp-wt/docs/HARNESS_KNOWHOW.md` §B4a -- which parses
    rather than matching text, and does not import, so a module name collision
    cannot decide what gets scanned.

    The regex this replaces was `r'"code":\\s*"([A-Z0-9_]+)"'`, and its
    character class was itself a bug fixed by hand: the earlier `[A-Z_]+`
    silently skipped any code containing a digit, making the completeness
    meta-guard vacuous for exactly the guards it exists to catch. Parsing has
    no character class to remember to widen, so that class of defect cannot
    recur.

    Measured before the swap (2026-08-22): on `contracts.py` both forms return
    the same 11 codes, so this is not a behaviour change. On a probe where a
    code appears inside a docstring and inside a comment, the regex returned
    three codes and the parse returned one -- the regex was also counting prose
    as guards, which would have let a fabricated witness satisfy the
    meta-guard.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(CONTRACTS_SOURCE)):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == "code"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                found.add(value.value)
    return found


@dataclass(frozen=True)
class GuardWitness:
    """A guard, plus one world where it must speak and one where it must not.

    `negative` is not optional padding. A guard that fires unconditionally
    passes any positive check; the negative witness is the only thing that
    separates "detects the condition" from "always fires".
    """

    positive: Callable[[], dict]
    negative: Callable[[], dict]
    why: str


# --- world builders -------------------------------------------------------

def _vault(tmp: Path, *, extra: dict[str, str] | None = None) -> dict:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "docs").mkdir(exist_ok=True)
    (tmp / "target.md").write_text("t", encoding="utf-8")
    (tmp / "docs" / "source.md").write_text("s [[target]]", encoding="utf-8")
    for rel, body in (extra or {}).items():
        path = tmp / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    return {"t1": VaultEntry(vault_id="t1", root=tmp, obsidian_vault_name="T1")}


def _query(registry, monkeypatch, *, cli_returns=None, cli_raises=False,
           active_vault="confirmed", path="target.md", max_results=50,
           fallback=True):
    """Drive the real pipeline with the external CLI replaced."""
    if cli_raises:
        def fetch(root, name, p):
            raise ObsidianUnavailable("obsidian CLI is not on PATH")
    else:
        def fetch(root, name, p):
            return list(cli_returns or [])
    monkeypatch.setattr(contracts, "fetch_backlinks", fetch)
    monkeypatch.setattr(contracts, "confirm_active_vault", lambda root: active_vault)
    monkeypatch.setattr(contracts, "FILESYSTEM_FALLBACK_ENABLED", fallback)
    # Both halves of the fallback switch, not just the flag. `contracts` reads
    # the environment at IMPORT time and binds `filesystem_fallback_backlinks`
    # to None when the fallback is off, and the production check is
    # `FILESYSTEM_FALLBACK_ENABLED and filesystem_fallback_backlinks is not
    # None`. Patching only the flag left that `and` half at whatever the
    # ambient environment produced, so the FILESYSTEM_FALLBACK_USED witness
    # passed or failed depending on how the suite was invoked -- adversarial
    # review F2 (2026-08-17), confirmed by running the witness alone under
    # VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0.
    monkeypatch.setattr(contracts, "filesystem_fallback_backlinks",
                        _real_filesystem_fallback if fallback else None)
    return contracts.query_backlinks("t1", path, max_results=max_results,
                                     registry=registry)


def _codes(result: dict) -> set[str]:
    return {check["code"] for check in result.get("review_checks", [])}


# --- the registry ---------------------------------------------------------
# Each entry is built lazily inside the test so every witness gets its own
# tmp_path and monkeypatch. The functions below take (tmp, monkeypatch).

def _w(positive, negative, why):
    return GuardWitness(positive=positive, negative=negative, why=why)


GUARD_WITNESSES: dict[str, Callable[[Path, pytest.MonkeyPatch], GuardWitness]] = {

    "TRUNCATED": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp), mp, max_results=1,
                       cli_returns=[{"file": "docs/source.md", "count": "1"},
                                    {"file": "target.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp, max_results=50,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "more results than max_results vs fewer",
    ),

    "FILESYSTEM_FALLBACK_USED": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp), mp, cli_raises=True, fallback=True),
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "live CLI unavailable with fallback on vs live CLI answering",
    ),

    "BASENAME_COLLISION": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp, extra={"docs/target.md": "duplicate name"}), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "a second file sharing the queried basename vs none",
    ),

    "SYMLINK_TARGET": lambda tmp, mp: _w(
        lambda: _query(_symlinked(tmp), mp, path="alias.md",
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        lambda: _query(_symlinked(tmp), mp, path="target.md",
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "querying the symlink vs querying the real file",
    ),

    "AMBIGUOUS_ACROSS_REGISTERED_VAULTS": lambda tmp, mp: _w(
        lambda: _query(_two_vaults(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        lambda: _query(_vault(tmp / "solo"), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "the same relative path existing in a second registered vault vs one vault",
    ),

    "ACTIVE_VAULT_MISMATCH": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp), mp, active_vault="mismatch",
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp, active_vault="confirmed",
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "cross-check reporting a different vault vs agreeing",
    ),

    "ACTIVE_VAULT_UNKNOWN": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp), mp, active_vault="unknown",
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp, active_vault="confirmed",
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "cross-check unavailable vs confirming",
    ),

    "ALL_RESULTS_OUT_OF_SCOPE": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "not/in/this/vault.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "every CLI result outside the vault root vs all inside",
    ),

    "SOME_RESULTS_OUT_OF_SCOPE": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"},
                                    {"file": "not/in/this/vault.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "a mix of in-scope and out-of-scope vs all in-scope",
    ),

    "ALL_RESULTS_FILTERED": lambda tmp, mp: _w(
        # forbidden-only: dropped, but NOT for the vault-scope reason
        lambda: _query(_vault(tmp, extra={"hidden_gold/g.md": "x"}), mp,
                       cli_returns=[{"file": "hidden_gold/g.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "every result dropped by the security filter vs none dropped",
    ),

    "SOME_RESULTS_FILTERED": lambda tmp, mp: _w(
        lambda: _query(_vault(tmp, extra={"hidden_gold/g.md": "x"}), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"},
                                    {"file": "hidden_gold/g.md", "count": "1"}]),
        lambda: _query(_vault(tmp), mp,
                       cli_returns=[{"file": "docs/source.md", "count": "1"}]),
        "one result dropped by the security filter vs none",
    ),
}


def _symlinked(tmp: Path) -> dict:
    registry = _vault(tmp)
    alias = tmp / "alias.md"
    if not alias.exists():
        alias.symlink_to(tmp / "target.md")
    return registry


def _two_vaults(tmp: Path) -> dict:
    first = tmp / "v1"
    second = tmp / "v2"
    registry = _vault(first)
    _vault(second)
    registry["t2"] = VaultEntry(vault_id="t2", root=second, obsidian_vault_name="T2")
    return registry


# --- documented exemptions ------------------------------------------------
# Reused verbatim in shape from this workspace's canonical mechanism,
# `concept-gate-taxonomy/test_guard_negative_coverage.py` (see
# `concept-gate-codex-mcp-wt/docs/HARNESS_KNOWHOW.md` §B4a). The point is that
# "known but not yet witnessed" belongs in CODE with a reason and an owner, not
# in a prose section of a handoff document where nothing checks it. Before this,
# unresolved items from the 2026-08-17 adversarial review lived only in
# `docs/ADVERSARIAL_REVIEW_GUARD_WITNESS_20260817.md`, so nothing failed when
# they went stale.
#
# Two rules the canonical version establishes and this one keeps:
#   1. An exemption that outlives its reason is a silent cap, so the list is
#      itself checked -- in both directions.
#   2. Do NOT fabricate a witness to empty this list. A mock-built negative
#      witness turns the gate green while proving nothing. If a guard cannot be
#      witnessed because the code already guarantees its condition, the question
#      is whether the guard is redundant, and that is a design decision a test
#      must not make on its own.

KNOWN_UNPROVEN: dict[str, str] = {
    # Empty, and that is the measured state: all 11 codes in contracts.py have
    # a positive and a negative witness. Kept because the mechanism must exist
    # BEFORE it is needed -- an empty list with live staleness checks is the
    # difference between "no exemptions" and "exemptions nobody tracks".
}


# --- the tests ------------------------------------------------------------

def test_every_guard_in_the_source_is_registered():
    """The meta-guard. Without it this file decays silently the moment
    someone adds a guard and forgets to add a witness -- the same "a gate
    hides a gate" failure this project has already hit twice."""
    in_source = _codes_in_source()
    assert in_source, (
        "the parse found no guard codes at all in contracts.py -- the scanner "
        "is broken, not the module. A completeness check over an empty set "
        "passes trivially, which is the exact failure this file exists to stop."
    )
    missing = in_source - set(GUARD_WITNESSES) - set(KNOWN_UNPROVEN)
    assert not missing, (
        f"guard code(s) in contracts.py with no registered witness: "
        f"{sorted(missing)}. Add a positive AND negative witness to "
        f"GUARD_WITNESSES; a guard nobody can show firing is not a guard. "
        f"If it genuinely cannot be witnessed yet, add it to KNOWN_UNPROVEN "
        f"with a reason -- but do not fabricate a mock-based witness."
    )


def test_the_registry_does_not_claim_guards_that_no_longer_exist():
    """The opposite drift: a witness left behind for a deleted guard reports
    coverage that no longer protects anything."""
    stale = set(GUARD_WITNESSES) - _codes_in_source()
    assert not stale, (
        f"registered witness(es) for code(s) absent from contracts.py: "
        f"{sorted(stale)}"
    )


def test_known_unproven_entries_are_not_stale():
    """An exemption list that outlives its reason is a silent cap.

    Checked in both directions, matching the canonical mechanism:
    an entry naming a code that no longer exists exempts nothing while looking
    like it exempts something -- and a future guard reusing that name would
    silently inherit the exemption. An entry that has since acquired a witness
    is simply obsolete.
    """
    in_source = _codes_in_source()
    vanished = sorted(code for code in KNOWN_UNPROVEN if code not in in_source)
    assert not vanished, (
        f"KNOWN_UNPROVEN names guard code(s) absent from contracts.py -- delete "
        f"these entries, and note that leaving them lets a future guard reusing "
        f"the name inherit the exemption: {vanished}"
    )
    now_witnessed = sorted(code for code in KNOWN_UNPROVEN
                           if code in GUARD_WITNESSES)
    assert not now_witnessed, (
        f"these code(s) now have a registered witness, so the exemption is "
        f"obsolete -- delete them from KNOWN_UNPROVEN: {now_witnessed}"
    )


@pytest.mark.parametrize("bogus,expected", [
    ("A_CODE_THAT_WAS_NEVER_IN_CONTRACTS", "absent from contracts.py"),
    # A real, already-witnessed code: the exemption is obsolete by definition.
    ("TRUNCATED", "obsolete"),
])
def test_the_staleness_check_itself_fires_on_a_bogus_entry(monkeypatch, bogus,
                                                           expected):
    """The exemption list is a checker, so it gets its own negative witness.

    Without this, `test_known_unproven_entries_are_not_stale` passing would be
    indistinguishable from it being unable to fail -- which is precisely the
    vacuous-guard shape this whole file is about. Both failure directions are
    exercised, because a check that catches only one of them is half a check.
    """
    monkeypatch.setitem(KNOWN_UNPROVEN, bogus, "injected by a negative witness")
    with pytest.raises(AssertionError, match=expected):
        test_known_unproven_entries_are_not_stale()


def test_the_fallback_witness_does_not_depend_on_import_time_configuration(
    tmp_path, monkeypatch
):
    """A witness whose verdict changes with the ambient environment is not a
    witness.

    `contracts` decides at IMPORT time whether the filesystem fallback exists
    at all, binding `filesystem_fallback_backlinks` to None when the operator
    has switched it off. Before this test existed, the
    FILESYSTEM_FALLBACK_USED witness patched only the boolean flag, so under
    `VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0` it could not fire and the witness
    FAILED -- but only when run alone. Inside the full suite it passed,
    because `test_contracts.py` calls `importlib.reload(contracts)` after
    `monkeypatch.delenv(...)`, and monkeypatch cannot undo a reload. That
    reload silently reconfigured the module to "fallback enabled" for every
    test that ran afterwards, masking the dependency.

    So this test builds the hostile world deliberately rather than trusting
    the suite to have wiped it, and restores the interpreter afterwards --
    including the reload, which is the part the leaking test forgot.
    """
    original = os.environ.get("VAULT_BACKLINKS_FILESYSTEM_FALLBACK")
    try:
        os.environ["VAULT_BACKLINKS_FILESYSTEM_FALLBACK"] = "0"
        importlib.reload(contracts)
        assert contracts.filesystem_fallback_backlinks is None, (
            "the hostile world this test needs no longer exists -- contracts "
            "kept the fallback bound with the switch off, so this test can no "
            "longer prove anything and must be rewritten, not deleted."
        )
        witness = GUARD_WITNESSES["FILESYSTEM_FALLBACK_USED"](tmp_path, monkeypatch)
        assert "FILESYSTEM_FALLBACK_USED" in _codes(witness.positive()), (
            "the fallback witness stopped firing when the fallback was "
            "disabled at import time. It is reporting the environment it ran "
            "in, not the guard it is supposed to witness."
        )
    finally:
        if original is None:
            os.environ.pop("VAULT_BACKLINKS_FILESYSTEM_FALLBACK", None)
        else:
            os.environ["VAULT_BACKLINKS_FILESYSTEM_FALLBACK"] = original
        importlib.reload(contracts)


def _assert_result_invariants(result: dict, where: str) -> None:
    """Properties that must hold in EVERY world, guard-firing or not.

    F5 (adversarial review 2026-08-17) said witness assertions ignore
    everything except the code, so a guard could fire with a wholly wrong
    payload. Measuring the claim narrowed it twice (2026-08-22):

      * All 11 guards carry exactly {code, required_action} -- there is no
        numeric payload INSIDE a check, so `_codes()` drops only prose.
      * The numeric fields are top-level, and two tests in test_contracts.py
        DO pin them with strong value-fixing oracles (`total == 5`,
        `dropped_by_reason["malformed"] == 1`, plus a negative assertion).
        Poison-confirmed: reverting `total` to the pre-v2 post-truncation bug
        fails test_max_results_truncation_is_flagged; zeroing
        `dropped_by_reason` fails test_drop_reasons_are_not_all_reported_as_
        vault_mismatch.

    What remained was the generalisation: those oracles pin values only in
    the two worlds those tests build. The other nine guards' worlds had
    nothing checking the numbers at all.

    Invariants rather than 11 hand-written `expected_payload` specs, on
    purpose. A per-guard expected payload would have to restate prose (which
    makes the test brittle the moment wording improves -- the
    "do not pin prose" caution in HARNESS_KNOWHOW) and would need a new spec
    for every guard added. These hold in all 22 witness worlds by
    construction, and they are the arithmetic a caller actually branches on.
    """
    assert result["returned_count"] == len(result["backlinks"] or []), (
        f"{where}: returned_count disagrees with the list it describes -- "
        f"{result['returned_count']} vs {len(result['backlinks'] or [])}"
    )
    # Pinned as an EQUALITY, split on the truncation signal, not as
    # `total >= returned_count`. The inequality was the first form and an
    # adversarial probe (haiku, 2026-08-22) defeated it: 19 of its 20 payload
    # mutations were caught, and the survivor was
    # `total_available = len(kept) + sum(drops.values())` -- which makes
    # `total` count results the security filter REJECTED. A caller then reads
    # "10 backlinks available" when 5 passed filtering, the same shape as the
    # pre-v2 bug where `total` was computed after truncation. The loose
    # inequality accepted it because an inflated total is still >=
    # returned_count.
    #
    # The exact relation is available from outside: when nothing was
    # truncated, every kept result was returned, so the two must be EQUAL;
    # when truncation happened, returned_count is the cap and total must be
    # strictly greater. `truncated` is observable via the TRUNCATED code.
    codes = {check["code"] for check in result["review_checks"]}
    if "TRUNCATED" in codes:
        assert result["total"] > result["returned_count"], (
            f"{where}: TRUNCATED was reported but total ({result['total']}) is "
            f"not above returned_count ({result['returned_count']}) -- either "
            f"the truncation claim is false or total was computed after the cut"
        )
    else:
        assert result["total"] == result["returned_count"], (
            f"{where}: nothing was truncated, so every result that passed "
            f"filtering was returned and total ({result['total']}) must equal "
            f"returned_count ({result['returned_count']}). A total ABOVE it "
            f"here means the count includes results this call dropped -- the "
            f"caller would read filtered-out entries as available evidence."
        )
    by_reason = result["dropped_by_reason"]
    assert set(by_reason) == {"malformed", "forbidden", "out_of_scope"}, (
        f"{where}: dropped_by_reason lost or gained a reason key: "
        f"{sorted(by_reason)}"
    )
    assert result["dropped_out_of_scope"] == by_reason["out_of_scope"], (
        f"{where}: dropped_out_of_scope ({result['dropped_out_of_scope']}) "
        f"disagrees with dropped_by_reason['out_of_scope'] "
        f"({by_reason['out_of_scope']}) -- the two fields describe the same "
        f"drops and a caller reading either must get the same answer"
    )
    assert all(count >= 0 for count in by_reason.values()), (
        f"{where}: a negative drop count: {by_reason}"
    )
    for check in result["review_checks"]:
        assert len(check.get("required_action", "")) >= 40, (
            f"{where}: {check.get('code')} carries a missing or stub "
            f"required_action -- review_required with no instruction is a "
            f"warning, not a contract"
        )


@pytest.mark.parametrize("code", sorted(GUARD_WITNESSES))
def test_result_invariants_hold_in_every_witness_world(code, tmp_path, monkeypatch):
    """The invariants above, in both worlds of every registered guard.

    This is the axis `_codes()` was missing, added once instead of eleven
    times. Twenty-two worlds get the arithmetic checked; a twelfth guard gets
    it for free.
    """
    witness = GUARD_WITNESSES[code](tmp_path, monkeypatch)
    _assert_result_invariants(witness.positive(), f"{code} positive")
    _assert_result_invariants(witness.negative(), f"{code} negative")


@pytest.mark.parametrize("code", sorted(GUARD_WITNESSES))
def test_guard_fires_on_its_positive_witness(code, tmp_path, monkeypatch):
    witness = GUARD_WITNESSES[code](tmp_path, monkeypatch)
    result = witness.positive()
    assert code in _codes(result), (
        f"{code} did not fire on the world it is supposed to detect "
        f"({witness.why}). Either the witness is wrong or the guard is "
        f"unreachable -- both are defects."
    )


@pytest.mark.parametrize("code", sorted(GUARD_WITNESSES))
def test_guard_stays_silent_on_its_negative_witness(code, tmp_path, monkeypatch):
    """Sensitivity without specificity is indistinguishable from a guard that
    always fires -- which is exactly how `review_required` became
    information-free once already."""
    witness = GUARD_WITNESSES[code](tmp_path, monkeypatch)
    result = witness.negative()
    assert code not in _codes(result), (
        f"{code} fired on a world where it should be silent ({witness.why}). "
        f"A guard that always speaks carries no information."
    )
