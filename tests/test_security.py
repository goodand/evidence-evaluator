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
