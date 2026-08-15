"""Same public interface as `obsidian_backend.py` (`fetch_backlinks`,
`ObsidianUnavailable`, `confirm_active_vault`), backed by
`evidence_evaluator.retrieval` instead of a direct `.vault-harness` import.

WHY THIS IS A NEW FILE, NOT AN IN-PLACE EDIT
---------------------------------------------
`docs/DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md` (evidence-evaluator package)
section 8 requires representative live-vault queries to be compared against
the old harness before it is retired, with material regressions recorded
rather than hidden. This module coexists with `obsidian_backend.py` so both
can be run against the same real vault paths for that comparison
(`tests/test_backend_parity.py`) instead of the swap happening silently.
`contracts.py` selects which one to use via `VAULT_BACKLINKS_BACKEND`
(default: `harness`, i.e. unchanged current behavior).

Everything in `contracts.py`/`security.py`/`registry.py` is UNCHANGED --
this only replaces the CLI-transport layer.

MEASURED SEMANTIC GAP -- link counts are lost through this path
-----------------------------------------------------------------
`obsidian_backend.fetch_backlinks()` returns raw
`{"file": str, "count": int}` entries straight from the CLI's
`counts format=json` output; `contracts.py` reads that `count` into
`link_count` per source. `evidence_evaluator.retrieval.obsidian`'s
`graph_paths()` normalizer strips counts and returns bare path strings only
-- that module's own consumers (`vault_search`'s graph walk) never needed a
per-edge count. Going through this backend means every `link_count` in the
final result becomes the fallback default (1), not the real per-file link
count, even when the real count is higher. This is a REAL loss, not a
theoretical one -- confirmed by reading `graph_paths()`'s source
(2026-08-15). It is recorded here and in the parity test rather than hidden;
do not treat this backend as a drop-in replacement until this is either
fixed upstream (a counts-preserving variant of `backlinks_only()`) or ruled
acceptable for this consumer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_DEFAULT_EVIDENCE_EVALUATOR_DIR = (Path.home() / "Desktop" / "Project_in_progress" /
                                   "evidence-evaluator")
_EVIDENCE_DIR = Path(os.environ.get("EVIDENCE_EVALUATOR_DIR",
                                    str(_DEFAULT_EVIDENCE_EVALUATOR_DIR)))
if str(_EVIDENCE_DIR) not in sys.path:
    sys.path.insert(0, str(_EVIDENCE_DIR))

try:
    from evidence_evaluator.retrieval.corpus import CanonicalPath, VaultCorpus
    from evidence_evaluator.retrieval.obsidian import ObsidianCliBackend
    from evidence_evaluator.retrieval.profile import VaultProfile
except ImportError as exc:  # pragma: no cover -- environment-dependent
    CanonicalPath = None
    ObsidianCliBackend = None
    VaultCorpus = None
    VaultProfile = None
    _IMPORT_ERROR = exc
else:
    _IMPORT_ERROR = None


class ObsidianUnavailable(RuntimeError):
    """The CLI could not be run, or its output could not be interpreted."""


def fetch_backlinks(vault_root: Path, obsidian_vault_name: str, path: str, *,
                    backend=None) -> list[dict]:
    """Return raw `[{"file": str, "count": 1}]` entries, or [] for none.

    Drop-in contract match for `obsidian_backend.fetch_backlinks` -- same
    signature, same raise-on-failure behavior -- except every `count` is the
    fallback default `1`, not a real per-file link count (see the module
    docstring's MEASURED SEMANTIC GAP).

    `backend` exists so tests can inject a fake `ObsidianCliBackend` without
    the real CLI or a real vault present, matching
    `obsidian_backend.fetch_backlinks`'s own `run_fn` parameter's purpose.
    """
    if backend is None:
        if ObsidianCliBackend is None or VaultProfile is None or CanonicalPath is None:
            raise ObsidianUnavailable(
                f"could not import evidence_evaluator.retrieval from "
                f"{_EVIDENCE_DIR}: {_IMPORT_ERROR}")
        profile = VaultProfile(root=vault_root, vault_name=obsidian_vault_name)
        backend = ObsidianCliBackend(profile)
    result = backend.backlinks_only(CanonicalPath(path))
    if not result.available:
        raise ObsidianUnavailable(
            f"obsidian CLI's backlinks call failed for {path!r}: "
            f"{'; '.join(result.warnings) or 'no error detail'}")
    return [{"file": item} for item in result.backlinks]


def confirm_active_vault(vault_root: Path, *, backend=None) -> str:
    """No equivalent check exists in `evidence_evaluator.retrieval`
    (2026-08-15: `confirm_active_vault`'s cross-check via a second CLI
    subcommand is specific to this server, not a shared utility yet).
    Always `"unknown"` here rather than silently `"confirmed"` -- same rule
    `obsidian_backend.py`'s own version follows: never assume active-vault
    status on a missing check.
    """
    return "unknown"


def filesystem_fallback_backlinks(vault_root: Path, path: str) -> list[str] | None:
    """Broader, lower-precision backlink scan for when the live CLI is
    unavailable -- called ONLY from `contracts.py`'s own fallback branch,
    never silently in place of a live answer. `None` means even this
    couldn't answer (path not found in this vault's own inventory either);
    the caller must not treat that the same as "zero backlinks".

    THIS IS NOT A DROP-IN FOR THE LIVE ANSWER. It counts a filename mention
    inside a code span (`` `CLAUDE.md` ``) the same as a real wikilink --
    `evidence_evaluator.retrieval.corpus`'s own `FILE_MENTION` regex is
    intentionally permissive, built for a different question ("what related
    documents exist") than this server's ("what did Obsidian's graph index
    right now"). Measured 2026-08-15 on the real `project-in-progress` vault:
    `CLAUDE.md` returned 50 entries this way against 5 from the live CLI --
    a caller that mistook this for a live-equivalent count would be
    wrong by 10x, not a rounding difference. `contracts.py` must always mark
    a result from this path with `backend_used: "filesystem_fallback"` and a
    `FILESYSTEM_FALLBACK_USED` review_check -- never as `"live"`.
    """
    if VaultCorpus is None or VaultProfile is None:
        return None
    profile = VaultProfile(root=vault_root, obsidian_enabled=False)
    corpus = VaultCorpus(profile)
    canonical = corpus.canonicalize(path)
    if canonical is None:
        return None
    return list(corpus.backlinks(canonical.relative))
