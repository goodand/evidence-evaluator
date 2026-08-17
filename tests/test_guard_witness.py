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
import re
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

    `[A-Z0-9_]+`, not `[A-Z_]+`. The narrower class silently skipped any
    future code containing a digit, which made the completeness meta-guard
    vacuous for exactly the guards it was written to catch. Confirmed by
    poison test (2026-08-17): appending `{"code": "STALE_INDEX_V2"}` to
    contracts.py with no registered witness left the meta-guard passing;
    widening the class makes it fail as intended. No current code has a
    digit -- this protects the guards nobody has written yet, which is the
    only thing this meta-guard is for.
    """
    return set(re.findall(r'"code":\s*"([A-Z0-9_]+)"', CONTRACTS_SOURCE))


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


# --- the tests ------------------------------------------------------------

def test_every_guard_in_the_source_is_registered():
    """The meta-guard. Without it this file decays silently the moment
    someone adds a guard and forgets to add a witness -- the same "a gate
    hides a gate" failure this project has already hit twice."""
    missing = _codes_in_source() - set(GUARD_WITNESSES)
    assert not missing, (
        f"guard code(s) in contracts.py with no registered witness: "
        f"{sorted(missing)}. Add a positive AND negative witness to "
        f"GUARD_WITNESSES; a guard nobody can show firing is not a guard."
    )


def test_the_registry_does_not_claim_guards_that_no_longer_exist():
    """The opposite drift: a witness left behind for a deleted guard reports
    coverage that no longer protects anything."""
    stale = set(GUARD_WITNESSES) - _codes_in_source()
    assert not stale, (
        f"registered witness(es) for code(s) absent from contracts.py: "
        f"{sorted(stale)}"
    )


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
