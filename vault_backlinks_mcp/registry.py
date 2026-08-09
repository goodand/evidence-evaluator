"""Vault registry: maps a caller-facing `vault_id` to a local root path and
the name Obsidian knows the vault by. Absolute workspace paths never live in
the server's own code -- only in this file (or the file it loads).

Why an allowlist and not a free-form path argument
----------------------------------------------------
A caller that could pass any `vault_root` directly could point this tool at
any directory on the machine, or at a path outside the vault(s) this server
is meant to serve -- an unregistered-directory read. Registering vault_id ->
root ahead of time makes "which directories can this tool ever touch" a
config-review question, not a runtime one.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

REGISTRY_ENV = "VAULT_BACKLINKS_REGISTRY"
DEFAULT_REGISTRY_PATH = Path.home() / ".config" / "vault-backlinks-mcp" / "registry.json"


class RegistryError(ValueError):
    """The registry file itself, or a lookup against it, is invalid."""


@dataclass(frozen=True)
class VaultEntry:
    vault_id: str
    root: Path
    obsidian_vault_name: str


def registry_path() -> Path:
    override = os.environ.get(REGISTRY_ENV)
    return Path(override) if override else DEFAULT_REGISTRY_PATH


def load_registry(path: Path | None = None) -> dict[str, VaultEntry]:
    path = path or registry_path()
    if not path.is_file():
        raise RegistryError(
            f"vault registry not found at {path}. Copy registry.example.json "
            f"there (or set {REGISTRY_ENV}) and fill in your own vault_id -> "
            f"root mappings.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RegistryError(f"vault registry at {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise RegistryError(f"vault registry at {path} must be a JSON object, got {type(data).__name__}")
    if data.get("contract_version") != "vault-registry-v1":
        raise RegistryError(f"vault registry at {path} has an unsupported contract_version")
    vaults = data.get("vaults")
    if not isinstance(vaults, dict) or not vaults:
        raise RegistryError(f"vault registry at {path} declares no vaults")
    out: dict[str, VaultEntry] = {}
    for vault_id, entry in vaults.items():
        # A malformed entry (e.g. a bare string instead of an object) must
        # become a RegistryError, not an uncaught AttributeError -- this
        # server's whole error contract (contracts.py) promises callers a
        # structured `error` field, never a raw exception escaping to the
        # MCP boundary. Reproduced 2026-08-09 (independent review of the
        # .vault-harness reuse contract, finding #6): {"bad": "not-an-object"}
        # crashed with `'str' object has no attribute 'get'`.
        if not isinstance(entry, dict):
            raise RegistryError(
                f"vault registry entry {vault_id!r} must be an object with "
                f"'root' and 'obsidian_vault_name', got {type(entry).__name__}")
        root = entry.get("root")
        name = entry.get("obsidian_vault_name")
        if not root or not name:
            raise RegistryError(
                f"vault registry entry {vault_id!r} needs both 'root' and "
                f"'obsidian_vault_name'")
        root_path = Path(root)
        if not root_path.is_dir():
            raise RegistryError(
                f"vault registry entry {vault_id!r} has root {root!r}, which "
                f"is not a directory on this machine")
        out[vault_id] = VaultEntry(vault_id=vault_id, root=root_path.resolve(),
                                   obsidian_vault_name=name)
    return out


def resolve_vault(vault_id: str, registry: dict[str, VaultEntry]) -> VaultEntry:
    entry = registry.get(vault_id)
    if entry is None:
        raise RegistryError(
            f"vault_id {vault_id!r} is not in the registry allowlist "
            f"(known: {sorted(registry)})")
    return entry
