from __future__ import annotations

import json
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from registry import RegistryError, load_registry  # noqa: E402


def _write(path: Path, data) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# --- regressions from the 2026-08-09 independent review of the
# .vault-harness reuse contract, finding #6 --------------------------------
# A malformed registry file must always fail closed as RegistryError, never
# escape as a raw exception -- contracts.py's whole design promises callers
# a structured `error` field, never an uncaught crash at the MCP boundary.

def test_non_object_entry_is_a_registry_error_not_attribute_error(tmp_path):
    """{"bad": "not-an-object"} used to crash with
    `'str' object has no attribute 'get'` instead of RegistryError."""
    path = _write(tmp_path / "registry.json", {
        "contract_version": "vault-registry-v1",
        "vaults": {"bad": "not-an-object"},
    })
    with pytest.raises(RegistryError, match="must be an object"):
        load_registry(path)


def test_non_object_entry_list_form_is_also_a_registry_error(tmp_path):
    path = _write(tmp_path / "registry.json", {
        "contract_version": "vault-registry-v1",
        "vaults": {"bad": ["root", "not", "a", "dict"]},
    })
    with pytest.raises(RegistryError, match="must be an object"):
        load_registry(path)


def test_non_object_top_level_is_a_registry_error(tmp_path):
    """The document itself being a bare list/string must not reach
    `data.get(...)` and crash before the vaults check ever runs."""
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(["not", "an", "object"]), encoding="utf-8")
    with pytest.raises(RegistryError, match="must be a JSON object"):
        load_registry(path)


def test_well_formed_entry_still_loads(tmp_path):
    vault_dir = tmp_path / "myvault"
    vault_dir.mkdir()
    path = _write(tmp_path / "registry.json", {
        "contract_version": "vault-registry-v1",
        "vaults": {"t": {"root": str(vault_dir), "obsidian_vault_name": "T"}},
    })
    registry = load_registry(path)
    assert registry["t"].obsidian_vault_name == "T"


# --- regression from the 2026-08-10 independent review round 2, finding #1
# (second half): non-string root/name types must be a RegistryError, not a
# raw TypeError from Path(root) --------------------------------------------

def test_non_string_root_is_a_registry_error_not_type_error(tmp_path):
    path = _write(tmp_path / "registry.json", {
        "contract_version": "vault-registry-v1",
        "vaults": {"t": {"root": ["a", "b"], "obsidian_vault_name": "T"}},
    })
    with pytest.raises(RegistryError, match="must have string"):
        load_registry(path)


def test_non_string_obsidian_vault_name_is_a_registry_error(tmp_path):
    vault_dir = tmp_path / "v"
    vault_dir.mkdir()
    path = _write(tmp_path / "registry.json", {
        "contract_version": "vault-registry-v1",
        "vaults": {"t": {"root": str(vault_dir), "obsidian_vault_name": 123}},
    })
    with pytest.raises(RegistryError, match="must have string"):
        load_registry(path)
