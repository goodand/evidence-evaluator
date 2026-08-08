"""Wraps `graph_for_candidate()` from the source workspace's existing,
already-working Obsidian CLI harness -- imported, not copied, per this
workspace's own rule against hand-duplicating code across trees (`CLAUDE.md`,
"worktree 사이로 파일을 손으로 복사하지 말 것"). `.vault-harness/` is a
protected dirty worktree there: read and import only, never edited.

MEASURED BEFORE WRITING THIS FILE (2026-08-08) -- vault switching over the
Obsidian CLI is genuinely unreliable, not a single clean failure mode:

- Querying `vault="perfect-structure-goodantak"` for `CLAUDE.md` (a file
  that exists ONLY in `Project_in_progress`) returned `Project_in_progress`'s
  real backlink data instead of "not found" -- with `cwd` left at an
  unrelated directory.
- Re-running the *same* query with `cwd` set to the target vault's own root
  (as `graph_for_candidate()` already does) sometimes then correctly
  answered "not found" -- so `cwd` is not irrelevant.
- But a genuinely-existing file *inside* that same target vault
  (`docs/stage3_adaptive_retrieval_recovery_architecture.md`, confirmed
  present on disk) was ALSO reported "not found" immediately after that
  vault appeared to become active.
- A raw vault-switch attempt hung past a 120s timeout on one attempt and
  returned near-instantly on others.

Net: switching which vault the CLI answers from is IPC-mediated, latency-
variable, and was observed to return both stale-vault and not-yet-indexed
answers in the same short test session. No sequence of `vault=`/`cwd`
arguments measured here reached a state where "the CLI says X" could be
trusted as "X is true of vault_id" without independent confirmation.

Consequence for this module and `security.py`: `graph_for_candidate()`'s own
retry-once-on-IPC-failure (source module, `graph_for_candidate` body) is kept
because it helps with transient single-call hiccups, but it is not treated as
sufficient. `contracts.py` cross-checks every returned path against the
target vault's own filesystem (`security.exists_under_root`) before trusting
it, regardless of what `vault=`/`cwd` claim to have selected.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Read-only reuse of a protected dirty worktree -- see module docstring.
_HARNESS_DIR = Path.home() / "Desktop" / "Project_in_progress" / ".vault-harness" / "vault-md-retrieval"
if str(_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_DIR))

try:
    from vault_md_harness import graph_for_candidate as _graph_for_candidate
except ImportError as exc:  # pragma: no cover -- environment-dependent
    _graph_for_candidate = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class ObsidianUnavailable(RuntimeError):
    """The CLI could not be run, or its output could not be interpreted."""


def fetch_backlinks(vault_root: Path, obsidian_vault_name: str, path: str, *,
                    graph_fn=None) -> list[dict]:
    """Return raw `[{"file": str, "count": str|int}]` entries, or [] for none.

    Raises ObsidianUnavailable if the harness module isn't importable, or if
    `graph_for_candidate()` reports every graph command failed (its own
    signal for "could not get anything from Obsidian for this candidate").

    `graph_fn` defaults to the imported `graph_for_candidate` and exists so
    tests can exercise this module's own error-handling and shaping logic
    without the real Obsidian CLI or `.vault-harness/` present -- it replaces
    the *external* call, not the logic under test here.
    """
    fn = graph_fn or _graph_for_candidate
    if fn is None:
        raise ObsidianUnavailable(
            f"could not import graph_for_candidate from {_HARNESS_DIR}: {_IMPORT_ERROR}")
    graph, errors = fn(vault_root, obsidian_vault_name, path)
    if graph is None:
        raise ObsidianUnavailable(
            f"obsidian CLI produced no usable result for {path!r} in vault "
            f"{obsidian_vault_name!r}: {'; '.join(errors) or 'no error detail'}")
    backlinks = graph.get("backlinks")
    if backlinks is None:
        # This one graph command failed while others (links/tags) may have
        # succeeded -- graph_for_candidate() only returns None overall when
        # ALL three failed, so a None here is backlinks-specific.
        raise ObsidianUnavailable(
            f"obsidian CLI's backlinks command failed for {path!r}: "
            f"{'; '.join(errors) or 'no error detail'}")
    if not isinstance(backlinks, list):
        raise ObsidianUnavailable(
            f"obsidian CLI backlinks output was not a list for {path!r}: {backlinks!r}")
    return backlinks
