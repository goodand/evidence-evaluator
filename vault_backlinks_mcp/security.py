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
MAX_BASENAME_COLLISIONS = 20


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
    """Literal-string check only -- see `is_forbidden_resolved` for the real
    gate. Kept because callers sometimes have a path with no vault attached
    (and because a literal match is a cheap early reject), but it is NOT
    sufficient on its own: it cannot see through a symlink alias, and it is
    case-sensitive while macOS's default APFS is not.

    Both gaps were reproduced end to end on 2026-08-09 (adversarial review
    findings #2/#4): `alias/gold.json` where `alias -> hidden_gold` returned
    False here and True from `exists_under_root`, so the query proceeded.
    """
    parts = {p.casefold() for p in Path(path).parts}
    return any(seg.casefold() in parts for seg in forbidden_segments)


def is_forbidden_resolved(vault: VaultEntry, path: str,
                          forbidden_segments: tuple[str, ...] = DEFAULT_FORBIDDEN_SEGMENTS) -> bool:
    """The real gate: forbidden if the literal path matches OR if the path,
    once resolved through symlinks, lands inside a forbidden directory.

    `is_forbidden` alone is bypassable two ways (see its docstring). This
    resolves first and checks the canonical location, which is what the
    module docstring's guarantee ("never accepted as a query target, even if
    the underlying CLI would happily return them") actually requires.
    """
    if is_forbidden(path, forbidden_segments):
        return True
    try:
        target = (vault.root / path).resolve()
        relative = target.relative_to(vault.root.resolve())
    except (OSError, ValueError):
        # Cannot resolve or resolves outside the root -- exists_under_root
        # rejects it separately; treat unresolvable as not-forbidden here so
        # this function has exactly one job.
        return False
    return is_forbidden(str(relative), forbidden_segments)


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
    """A backlink source that is itself a symlink -- or reached through a
    symlinked ANCESTOR directory -- should not be reported as a canonical
    authority. See notes/audits/vault/symlink-vs-moc-2026-07-30 in the source
    workspace for why a symlink and its target are not interchangeable for
    provenance purposes.

    Checking only the final component is not sufficient: reproduced
    2026-08-09 (independent adversarial review of the .vault-harness reuse
    contract) -- `alias/target.md` where `alias` is a symlinked directory and
    `target.md` itself is a real file passed `exists_under_root() == True`
    while this check (final-component-only) returned False. If Obsidian does
    not index that symlinked-parent path, the result is a confident, wrong
    zero: `review_required=False`, `total=0`, with no signal that the path is
    unqueryable rather than genuinely backlink-free.
    """
    current = vault.root
    for part in Path(path).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def find_basename_collisions(vault: VaultEntry, path: str) -> list[str]:
    """Other files under the vault root sharing this path's basename.

    A non-empty result means the exact path the caller asked about is
    ambiguous with at least one other file if anything ever resolves this
    target by basename instead of exact path -- the vault-workspace failure
    mode this server exists partly to avoid (same-named files across
    worktrees resolved to the wrong one).

    Forbidden paths are excluded from the result via `is_forbidden_resolved`,
    not the literal-only `is_forbidden`. Without that, this function leaked
    protected paths two different ways, both reproduced end to end:

    - 2026-08-09 (adversarial review finding #3): a vault containing both
      `target.md` and `hidden_gold/target.md` produced a BASENAME_COLLISION
      `required_action` naming `hidden_gold/target.md` verbatim.
    - 2026-08-09 (independent review of the .vault-harness reuse contract,
      finding #5): a plain-looking path (`docs/target.md`) that is itself a
      *symlink into* `hidden_gold/target.md` passed the literal `is_forbidden`
      check (its own path string names no forbidden segment) and still
      appeared in the collision list -- the same symlink-alias bypass that
      `is_forbidden_resolved` exists to close, just reached through this
      function instead of the main query path.

    Bounded to `MAX_BASENAME_COLLISIONS` matches. This does not fix the
    underlying cost (a full `rglob()` still walks the whole vault tree on
    every call, and a vault with zero or few matches pays that full cost
    regardless of the cap) -- it only stops early once enough matches are
    found and prevents an unbounded result list. A real fix would need an
    index, which the DO-NOT-BUILD ruling in this package's module docstring
    already rejected for correctness reasons (staleness), not cost reasons;
    trading correctness for speed here would reopen that same rejected
    tradeoff. Reproduced 2026-08-10 (independent review round 2, finding #5):
    no cap existed before this.
    """
    name = Path(path).name
    out = []
    for p in vault.root.rglob(name):
        if len(out) >= MAX_BASENAME_COLLISIONS:
            break
        try:
            relative = str(p.relative_to(vault.root))
        except ValueError:
            continue
        if relative == path or is_forbidden_resolved(vault, relative):
            continue
        out.append(relative)
    return sorted(out)
