"""Every refusal query_backlinks can emit must carry a machine-readable code,
and every code must prove it can fire and stay silent.

WHY THIS FILE EXISTS -- F7, verified 2026-08-22 on this tree
------------------------------------------------------------
The guard-witness registry (test_guard_witness.py) audits review_checks CODES.
But the validation error paths -- max_results, path security, forbidden
segments, registry lookup, existence -- return `_error_result(...)` with only a
prose `error` message and NO code. So `_codes_in_source()` structurally cannot
see them, they can never enter GUARD_WITNESSES, and the registry's "every
guard" claim silently meant "every guard that happens to be expressed as a
review_checks code". A new refusal added tomorrow would join the suite with no
witness requirement at all.

Same mechanization as the review codes, applied to the refusal channel:
`_error_result` now REQUIRES an `error_code`, call sites carry it as a literal
(AST-visible), and this registry pairs each code with a world where it fires
and shares one world where every code must stay silent.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path
from typing import Callable

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

import contracts  # noqa: E402
from registry import VaultEntry  # noqa: E402
from obsidian_backend import ObsidianUnavailable  # noqa: E402

CONTRACTS_SOURCE = (PKG / "contracts.py").read_text(encoding="utf-8")


def _error_codes_in_source() -> set[str]:
    """String literals passed as `error_code=` at call sites, via AST.

    A keyword-argument variant of the dict-literal scan used for review codes
    (test_guard_witness._codes_in_source) -- parsing, not regex, for the same
    reasons: no character class to forget, and prose mentions don't count.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(CONTRACTS_SOURCE)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if (keyword.arg == "error_code"
                    and isinstance(keyword.value, ast.Constant)
                    and isinstance(keyword.value.value, str)):
                found.add(keyword.value.value)
    return found


# --- worlds -------------------------------------------------------------------

def _vault(tmp: Path, *, symlink_trap: bool = False) -> dict:
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "docs").mkdir(exist_ok=True)
    (tmp / "target.md").write_text("t", encoding="utf-8")
    (tmp / "docs" / "source.md").write_text("s [[target]]", encoding="utf-8")
    if symlink_trap:
        (tmp / "hidden_gold").mkdir(exist_ok=True)
        (tmp / "hidden_gold" / "g.md").write_text("x", encoding="utf-8")
        alias = tmp / "alias"
        if not alias.exists():
            alias.symlink_to(tmp / "hidden_gold")
    return {"t1": VaultEntry(vault_id="t1", root=tmp, obsidian_vault_name="T1")}


def _query(registry, monkeypatch, *, path="target.md", max_results=50,
           vault_id="t1", raise_unavailable=False):
    if raise_unavailable:
        def fetch(root, name, p):
            raise ObsidianUnavailable("obsidian CLI is not on PATH")
        monkeypatch.setattr(contracts, "fetch_backlinks", fetch)
        monkeypatch.setattr(contracts, "FILESYSTEM_FALLBACK_ENABLED", False)
        monkeypatch.setattr(contracts, "filesystem_fallback_backlinks", None)
    else:
        monkeypatch.setattr(contracts, "fetch_backlinks",
                            lambda root, name, p: [{"file": "docs/source.md",
                                                    "count": "1"}])
    return contracts.query_backlinks(vault_id, path, max_results=max_results,
                                     registry=registry)


ERROR_CODE_WITNESSES: dict[str, Callable] = {
    "INVALID_MAX_RESULTS":
        lambda tmp, mp: _query(_vault(tmp), mp, max_results=0),
    "INVALID_PATH":
        lambda tmp, mp: _query(_vault(tmp), mp, path="../escape.md"),
    "PATH_FORBIDDEN":
        lambda tmp, mp: _query(_vault(tmp, symlink_trap=True), mp,
                               path="hidden_gold/g.md"),
    "PATH_FORBIDDEN_RESOLVED":
        lambda tmp, mp: _query(_vault(tmp, symlink_trap=True), mp,
                               path="alias/g.md"),
    "REGISTRY_ERROR":
        lambda tmp, mp: _query({}, mp, vault_id="no-such-vault"),
    "PATH_NOT_IN_VAULT":
        lambda tmp, mp: _query(_vault(tmp), mp, path="docs/missing.md"),
    "BACKEND_UNAVAILABLE":
        lambda tmp, mp: _query(_vault(tmp), mp, raise_unavailable=True),
}

KNOWN_UNPROVEN: dict[str, str] = {
    # Empty by measurement; kept live so exemptions are tracked, not remembered.
}


# --- completeness, both directions ---------------------------------------------

def test_every_error_code_in_the_source_is_registered():
    in_source = _error_codes_in_source()
    assert in_source, (
        "no error_code literals found in contracts.py -- either the refusal "
        "channel has not been coded yet (this file is written first, TDD), or "
        "the scanner broke; an empty set must fail, not pass trivially."
    )
    missing = in_source - set(ERROR_CODE_WITNESSES) - set(KNOWN_UNPROVEN)
    assert not missing, (
        f"error code(s) emitted in contracts.py with no registered witness: "
        f"{sorted(missing)}"
    )


def test_the_registry_does_not_claim_codes_that_no_longer_exist():
    stale = set(ERROR_CODE_WITNESSES) - _error_codes_in_source()
    assert not stale, (
        f"registered witness(es) for error code(s) contracts.py never emits: "
        f"{sorted(stale)}"
    )


def test_known_unproven_entries_are_not_stale():
    in_source = _error_codes_in_source()
    vanished = sorted(c for c in KNOWN_UNPROVEN if c not in in_source)
    assert not vanished, (
        f"KNOWN_UNPROVEN names error code(s) absent from contracts.py -- "
        f"delete these entries: {vanished}"
    )
    obsolete = sorted(c for c in KNOWN_UNPROVEN if c in ERROR_CODE_WITNESSES)
    assert not obsolete, (
        f"these code(s) now have a witness; the exemption is obsolete: {obsolete}"
    )


@pytest.mark.parametrize("bogus,expected", [
    ("A_REFUSAL_NOBODY_EMITS", "absent from contracts.py"),
    ("INVALID_MAX_RESULTS", "obsolete"),
])
def test_the_staleness_check_itself_fires_on_a_bogus_entry(monkeypatch, bogus,
                                                           expected):
    monkeypatch.setitem(KNOWN_UNPROVEN, bogus, "injected by a negative witness")
    with pytest.raises(AssertionError, match=expected):
        test_known_unproven_entries_are_not_stale()


# --- the witnesses ---------------------------------------------------------------

@pytest.mark.parametrize("code", sorted(ERROR_CODE_WITNESSES))
def test_refusal_fires_with_its_code(code, tmp_path, monkeypatch):
    result = ERROR_CODE_WITNESSES[code](tmp_path, monkeypatch)
    assert result["error"] is not None, (
        f"the world for {code} did not produce a refusal at all -- the witness "
        f"is wrong, not necessarily the code"
    )
    assert result.get("error_code") == code, (
        f"refusal happened but carried {result.get('error_code')!r} instead of "
        f"{code} -- the caller cannot branch on prose"
    )
    assert result["backend_used"] == "none"


def test_a_successful_query_carries_no_error_code(tmp_path, monkeypatch):
    """The shared negative witness. Without it, stamping every result with an
    error code would satisfy all the positive cases above."""
    result = _query(_vault(tmp_path), monkeypatch)
    assert result["error"] is None
    assert result.get("error_code") is None, (
        f"a successful answer carried error_code={result.get('error_code')!r}"
    )
