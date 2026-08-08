"""Path safety and gold-leak guards.

These exist because the tool this module supports shells out to an external
binary (the Obsidian CLI) whose behaviour was independently measured, not
assumed, before this server was written -- see `obsidian_backend.py`'s module
docstring for what that measurement found and why it changes this module's
design.
"""

from __future__ import annotations

from pathlib import Path

from registry import VaultEntry


class PathSecurityError(ValueError):
    """A requested or CLI-returned path violated a safety rule."""


# Paths that must never be exposed as a backlink source or accepted as a
# query target, even if the underlying CLI would happily return them.
# Extend this list per-deployment; it is intentionally small and explicit --
# see `contract.py` in the evidence-evaluator package for the same
# "explicit list, not a heuristic" choice and why.
DEFAULT_FORBIDDEN_SEGMENTS = ("hidden_gold", ".git", "node_modules")


def validate_relative_path(raw: str) -> str:
    """Reject anything that is not a clean, relative, non-traversing path.

    Mirrors `evidence_evaluator.contract._rel` (evidence-evaluator package,
    2026-08-08) -- same rule, same reason: a caller-supplied path must not
    reach outside the vault root via an absolute path or `..`.
    """
    if not isinstance(raw, str) or not raw:
        raise PathSecurityError("path must be a non-empty string")
    if raw.startswith("/") or raw.startswith("~"):
        raise PathSecurityError(f"path must be relative, got {raw!r}")
    if ".." in Path(raw).parts:
        raise PathSecurityError(f"path must not contain '..', got {raw!r}")
    return raw


def is_forbidden(path: str, forbidden_segments: tuple[str, ...] = DEFAULT_FORBIDDEN_SEGMENTS) -> bool:
    parts = set(Path(path).parts)
    return any(seg in parts for seg in forbidden_segments)


def exists_under_root(vault: VaultEntry, path: str) -> bool:
    """Cross-check: does this path actually exist under the vault's own root?

    This is the load-bearing safety check in this server. `obsidian_backend.py`
    measured that the Obsidian CLI's `vault=` argument does not reliably scope
    a query to the named vault -- an unregistered or wrong vault name can
    silently return another vault's results. A CLI answer is trusted only
    after every path in it is confirmed to exist on disk under the
    `vault_id` the caller actually asked for; anything that doesn't is
    dropped, not silently kept.
    """
    try:
        target = (vault.root / path).resolve()
    except (OSError, ValueError):
        return False
    try:
        target.relative_to(vault.root)
    except ValueError:
        return False  # resolved outside the root -- e.g. a symlink escape
    return target.is_file()


def is_symlink_under_root(vault: VaultEntry, path: str) -> bool:
    """A backlink source that is itself a symlink should not be reported as
    a canonical authority -- see notes/audits/vault/symlink-vs-moc-2026-07-30
    in the source workspace for why a symlink and its target are not
    interchangeable for provenance purposes."""
    candidate = vault.root / path
    return candidate.is_symlink()


def find_basename_collisions(vault: VaultEntry, path: str) -> list[str]:
    """Other files under the vault root sharing this path's basename.

    A non-empty result means the exact path the caller asked about is
    ambiguous with at least one other file if anything ever resolves this
    target by basename instead of exact path -- the vault-workspace failure
    mode this server exists partly to avoid (same-named files across
    worktrees resolved to the wrong one).
    """
    name = Path(path).name
    return sorted(
        str(p.relative_to(vault.root)) for p in vault.root.rglob(name)
        if str(p.relative_to(vault.root)) != path
    )
