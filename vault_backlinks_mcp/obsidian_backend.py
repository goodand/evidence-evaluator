"""Wraps `graph_for_candidate()` from the source workspace's existing,
already-working Obsidian CLI harness -- imported, not copied, per this
workspace's own rule against hand-duplicating code across trees (`CLAUDE.md`,
"worktree 사이로 파일을 손으로 복사하지 말 것"). `.vault-harness/` is a
protected dirty worktree there: read and import only, never edited.

MEASURED BEFORE WRITING THIS FILE, then re-diagnosed (2026-08-08). Two
INDEPENDENT defects were confirmed; an earlier draft of this docstring
conflated them into one vague "vault switching is unreliable" claim, which
was wrong about the second.

**Defect 1 -- `vault=` is ignored; `cwd` is what selects the vault.**
With `cwd` at `Project_in_progress`, querying
`vault="perfect-structure-goodantak"` for `CLAUDE.md` -- a file that exists
only in `Project_in_progress` -- returns `Project_in_progress`'s real
backlinks. Running the identical query with `cwd` set to the goodantak vault
root correctly answers `Error: File "CLAUDE.md" not found.` So the CLI
answers from whatever vault `cwd` sits in and the `vault=` argument does not
override it. `graph_for_candidate()` already passes `cwd=vault_root`, which
is why reusing it (rather than shelling out directly) matters.

**Defect 2 -- Obsidian does not index symlinked paths.**
`docs/stage3_adaptive_retrieval_recovery_architecture.md` in the goodantak
vault was reported "not found" even with `cwd` correct. It is a **symlink**:
that vault keeps its canonical files under `knowledge/files/markdown/` and
exposes them through symlinked directories (27 of its 97 markdown paths are
symlinks). Querying the canonical path
`knowledge/files/markdown/docs/stage3_adaptive_retrieval_recovery_architecture.md`
returns 4 real backlinks. So this was never a vault-switching problem --
Obsidian simply does not resolve symlinks into its index, and the earlier
"a genuinely-existing file was also reported not-found" observation had a
completely different cause than the one it was filed under.

Checked across all three registered vaults after a report that *some*
symlinks do appear in Obsidian: **no queryable symlink was found.** 18 of 18
sampled symlinked `.md` paths (8 in goodantak, 10 in Project_in_progress)
returned "not found"; `perfect-structure` has zero symlinks; neither vault
has exclusion rules (`.obsidian/app.json` is `{}` in both); and the same
"not found" holds for `links`, `tags`, and `wordcount`, so it is not
specific to `backlinks`. The canonical path works for all of them.

What *does* appear, and is the likely source of that impression: the
canonical file is indexed and reachable by its **basename** through a
wikilink. `knowledge/.../wiki/stage3-retrieval-evaluation-moc.md` writes
`[[stage3_adaptive_retrieval_recovery_architecture]]`, and `obsidian links`
resolves it to the canonical `knowledge/files/markdown/docs/...` path -- not
to the `docs/...` symlink. So the note is visible and linkable in the app
while its symlinked path is not addressable by the CLI. Both observations
are true at once; they are about different paths to the same note.

Consequences, one per defect:

1. `contracts.py` cross-checks every returned path against the target
   vault's own filesystem (`security.exists_under_root`) before trusting it,
   so a `cwd`-induced wrong-vault answer is dropped rather than returned.
   This is the load-bearing safety property of this server.
2. `security.is_symlink_under_root` raises `SYMLINK_TARGET` on the queried
   path, so a symlink query returns "0 results + SYMLINK_TARGET +
   ALL_RESULTS_OUT_OF_SCOPE" rather than a bare, confident zero. Verified
   end to end against the real goodantak vault: the symlink path yields that
   flagged empty result and the canonical path yields the 4 real backlinks.

`graph_for_candidate()`'s own retry-once-on-IPC-failure is kept for transient
hiccups but is not treated as sufficient for either defect.

PORTABILITY (finding #2, independent review of this reuse contract,
2026-08-09) -- the harness directory used to be a hardcoded
`Path.home() / "Desktop" / "Project_in_progress" / ...`, which only worked on
the one machine, one user account, and one directory layout this server was
first written under. `VAULT_HARNESS_DIR` now overrides it; the hardcoded path
remains only as the default for that one original deployment. This does not
version the harness's API -- a caller that needs that should still pin a
harness commit externally.

SINGLE-CALL BACKLINKS (finding #4, same review) -- `graph_for_candidate()`
always issues three CLI calls (`backlinks`, `links`, `tags`) because it is a
general graph fetch shared with the retrieval harness's own callers. This
server only ever reads the `backlinks` key, so the other two calls are pure
overhead against an IPC channel already measured as unreliable (see Defect 1
above) -- three times the chance of a transient failure for one-third the
useful data. `fetch_backlinks()` below builds and runs only the `backlinks`
command, reusing the harness's own `run()` subprocess wrapper and
`parse_cli_output()` parser (both already-public, already-tested names in
`vault_md_harness`) rather than re-implementing subprocess handling or output
parsing. It duplicates only the small piece that has to change: which
command to send. The retry-once-on-transient-failure behavior is copied
verbatim from `graph_for_candidate()` since the protected harness file itself
cannot be edited to expose it as a shared helper.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Read-only reuse of a protected dirty worktree -- see module docstring.
_DEFAULT_HARNESS_DIR = (Path.home() / "Desktop" / "Project_in_progress" /
                        ".vault-harness" / "vault-md-retrieval")
_HARNESS_DIR = Path(os.environ.get("VAULT_HARNESS_DIR", str(_DEFAULT_HARNESS_DIR)))
if str(_HARNESS_DIR) not in sys.path:
    sys.path.insert(0, str(_HARNESS_DIR))

try:
    from vault_md_harness import OBSIDIAN as _OBSIDIAN
    from vault_md_harness import parse_cli_output as _parse_cli_output
    from vault_md_harness import run as _run
except ImportError as exc:  # pragma: no cover -- environment-dependent
    _OBSIDIAN = None
    _parse_cli_output = None
    _run = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class ObsidianUnavailable(RuntimeError):
    """The CLI could not be run, or its output could not be interpreted."""


def fetch_backlinks(vault_root: Path, obsidian_vault_name: str, path: str, *,
                    run_fn=None) -> list[dict]:
    """Return raw `[{"file": str, "count": str|int}]` entries, or [] for none.

    Issues exactly one Obsidian CLI call (`backlinks`), not three -- see
    "SINGLE-CALL BACKLINKS" in this module's docstring for why the shared
    `graph_for_candidate()` is not used here.

    `run_fn` defaults to the imported harness `run()` and exists so tests can
    exercise this module's own error-handling and shaping logic without the
    real Obsidian CLI or `.vault-harness/` present -- it replaces the
    *external* call, not the logic under test here.
    """
    runner = run_fn or _run
    if runner is None or _parse_cli_output is None or _OBSIDIAN is None:
        raise ObsidianUnavailable(
            f"could not import run/parse_cli_output/OBSIDIAN from "
            f"{_HARNESS_DIR}: {_IMPORT_ERROR}")
    command = [_OBSIDIAN, "backlinks", f"vault={obsidian_vault_name}",
              f"path={path}", "counts", "format=json"]
    result = runner(command, cwd=vault_root)
    output = result.stdout.strip()
    error = result.stderr.strip()
    if result.returncode != 0 or "unable to find Obsidian" in output:
        # Retry once, exactly like graph_for_candidate() -- transient IPC
        # hiccups are common enough that the harness itself treats one retry
        # as normal, not exceptional.
        time.sleep(0.2)
        result = runner(command, cwd=vault_root)
        output = result.stdout.strip()
        error = result.stderr.strip()
    if result.returncode != 0 or "unable to find Obsidian" in output:
        raise ObsidianUnavailable(
            f"obsidian CLI's backlinks command failed for {path!r}: "
            f"{error or output or 'no error detail'}")
    backlinks = _parse_cli_output(output)
    if not isinstance(backlinks, list):
        raise ObsidianUnavailable(
            f"obsidian CLI backlinks output was not a list for {path!r}: {backlinks!r}")
    return backlinks
