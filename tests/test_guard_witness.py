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


CONTRACTS_SOURCE = (PKG / "contracts.py").read_text(encoding="utf-8")


def _codes_in_source() -> set[str]:
    """Guard codes as they actually appear in the module under test."""
    return set(re.findall(r'"code":\s*"([A-Z_]+)"', CONTRACTS_SOURCE))


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
