from __future__ import annotations

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from registry import VaultEntry  # noqa: E402
from security import (PathSecurityError, exists_under_root, find_basename_collisions,
                      is_forbidden, is_symlink_under_root, validate_relative_path)  # noqa: E402


@pytest.fixture()
def vault(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("a", encoding="utf-8")
    (tmp_path / "docs" / "sub").mkdir()
    (tmp_path / "docs" / "sub" / "a.md").write_text("a2", encoding="utf-8")
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "gold.json").write_text("{}", encoding="utf-8")
    (tmp_path / "docs" / "link.md").symlink_to(tmp_path / "docs" / "a.md")
    return VaultEntry(vault_id="t", root=tmp_path, obsidian_vault_name="T")


def test_validate_relative_path_rejects_absolute():
    with pytest.raises(PathSecurityError):
        validate_relative_path("/etc/passwd")


def test_validate_relative_path_rejects_traversal():
    with pytest.raises(PathSecurityError):
        validate_relative_path("docs/../../etc/passwd")


def test_validate_relative_path_rejects_tilde():
    with pytest.raises(PathSecurityError):
        validate_relative_path("~/secrets.md")


def test_validate_relative_path_accepts_clean_relative():
    assert validate_relative_path("docs/a.md") == "docs/a.md"


def test_is_forbidden_flags_hidden_gold():
    assert is_forbidden("hidden_gold/gold.json") is True
    assert is_forbidden("docs/a.md") is False


def test_exists_under_root_true_for_real_file(vault):
    assert exists_under_root(vault, "docs/a.md") is True


def test_exists_under_root_false_for_missing_file(vault):
    assert exists_under_root(vault, "docs/missing.md") is False


def test_exists_under_root_false_for_traversal_that_resolves_outside(vault):
    # Even if validate_relative_path is bypassed upstream, this must still
    # refuse to confirm existence outside the vault root.
    assert exists_under_root(vault, "../../../../etc/hosts") is False


def test_is_symlink_under_root_detects_symlink(vault):
    assert is_symlink_under_root(vault, "docs/link.md") is True
    assert is_symlink_under_root(vault, "docs/a.md") is False


def test_find_basename_collisions_finds_the_other_file(vault):
    collisions = find_basename_collisions(vault, "docs/a.md")
    assert collisions == ["docs/sub/a.md"]


def test_find_basename_collisions_empty_when_unique(vault):
    assert find_basename_collisions(vault, "docs/link.md") == []


# --- regressions from the 2026-08-09 adversarial review -------------------
# All three bypasses below were reproduced end-to-end against the real
# pipeline before being fixed. None of the 21 pre-existing tests caught any
# of them: test_is_forbidden_flags_hidden_gold only ever used an exact-case,
# non-symlinked literal path.

def test_is_forbidden_is_case_insensitive(vault):
    """macOS's default APFS is case-insensitive, so a mixed-case spelling
    reaches the same file while a case-sensitive check waves it through."""
    assert is_forbidden("Hidden_Gold/secret.md") is True
    assert is_forbidden("HIDDEN_GOLD/secret.md") is True


def test_is_forbidden_resolved_sees_through_a_symlink_alias(tmp_path):
    """`alias -> hidden_gold` made `alias/gold.json` clear both the literal
    forbidden check and exists_under_root, reaching the external CLI."""
    from security import is_forbidden_resolved
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "gold.json").write_text("{}", encoding="utf-8")
    (tmp_path / "alias").symlink_to(tmp_path / "hidden_gold")
    v = VaultEntry(vault_id="t", root=tmp_path.resolve(), obsidian_vault_name="T")

    assert is_forbidden("alias/gold.json") is False, "literal check cannot see it"
    assert is_forbidden_resolved(v, "alias/gold.json") is True, "resolved check must"


def test_find_basename_collisions_excludes_forbidden_paths(tmp_path):
    """The collision list was the one path not gated by is_forbidden, and it
    disclosed `hidden_gold/target.md` verbatim in a review_check message."""
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "target.md").write_text("gold", encoding="utf-8")
    (tmp_path / "target.md").write_text("real", encoding="utf-8")
    v = VaultEntry(vault_id="t", root=tmp_path.resolve(), obsidian_vault_name="T")

    assert find_basename_collisions(v, "target.md") == []


# --- regressions from the 2026-08-09 independent review of this reuse
# contract (a separate pass from the adversarial review above; findings
# numbered independently in that report) ----------------------------------

def test_is_symlink_under_root_detects_a_symlinked_ancestor(tmp_path):
    """Finding #1: checking only the final path component missed a symlinked
    PARENT directory. `alias/target.md` where `alias` is a symlinked
    directory and `target.md` is a real file passed exists_under_root()=True
    while the old final-component-only check returned False -- a confident,
    wrong zero if Obsidian does not index that path."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    (real_dir / "target.md").write_text("# t", encoding="utf-8")
    (tmp_path / "alias").symlink_to(real_dir, target_is_directory=True)
    v = VaultEntry(vault_id="t", root=tmp_path.resolve(), obsidian_vault_name="T")

    assert exists_under_root(v, "alias/target.md") is True
    assert is_symlink_under_root(v, "alias/target.md") is True
    # The final component itself being a real file must not mask the
    # symlinked ancestor above it.
    assert is_symlink_under_root(v, "docs/a.md") is False


def test_find_basename_collisions_excludes_a_symlink_alias_into_forbidden(tmp_path):
    """Finding #5: a plain-looking path (docs/target.md) that is ITSELF a
    symlink into hidden_gold/target.md passed the literal is_forbidden check
    (its own path string names no forbidden segment) and still appeared in
    the collision list -- the same symlink-alias bypass is_forbidden_resolved
    exists to close, reached through this function instead of the main query
    path."""
    (tmp_path / "target.md").write_text("# public", encoding="utf-8")
    gold = tmp_path / "hidden_gold"
    gold.mkdir()
    (gold / "target.md").write_text("# secret", encoding="utf-8")
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "target.md").symlink_to(gold / "target.md")
    v = VaultEntry(vault_id="t", root=tmp_path.resolve(), obsidian_vault_name="T")

    assert is_forbidden("docs/target.md") is False, "literal check cannot see it"
    assert find_basename_collisions(v, "target.md") == []


def test_find_basename_collisions_is_capped(tmp_path):
    """Finding #5 (independent review round 2, 2026-08-10): no cap existed
    before this -- a vault with many same-named files returned an unbounded
    list."""
    from security import MAX_BASENAME_COLLISIONS
    (tmp_path / "target.md").write_text("root", encoding="utf-8")
    for i in range(MAX_BASENAME_COLLISIONS + 10):
        d = tmp_path / f"dup{i}"
        d.mkdir()
        (d / "target.md").write_text(str(i), encoding="utf-8")
    v = VaultEntry(vault_id="t", root=tmp_path.resolve(), obsidian_vault_name="T")

    assert len(find_basename_collisions(v, "target.md")) == MAX_BASENAME_COLLISIONS
