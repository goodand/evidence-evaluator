"""Builds the `vault_backlinks` result and enforces every safety rule in one
place, so `server.py` stays a thin MCP registration and nothing calls
`obsidian_backend` without going through these checks.

DESIGN NOTE -- why this is live-only, no indexed backend
-----------------------------------------------------------
The original design proposal for this tool (`concept-gate-taxonomy` workspace,
`DESIGN_PROPOSAL_vault_backlinks_mcp_server_20260807.md`) specified a
dual-backend server: an always-available SQLite index plus this CLI as an
optional live cross-check. An independent adversarial review measured that
the indexed backend was 3 days stale, missed half of a file's real backlinks
(5 indexed vs 10 live), and reported an already-resolved orphan as still an
orphan -- i.e. it produced confident, wrong answers, which is worse than an
honest failure. That review's verdict was **DO-NOT-BUILD** the dual-backend
design; its documented fallback, if a live-agent-facing tool is still needed,
was live-only with honest failure and no indexed fallback. This module is
that fallback, built after `evidence-evaluator` (2026-08-08) demonstrated the
cross-agent need the DO-NOT-BUILD ruling had left as unconfirmed.

The live call itself (`obsidian_backend.fetch_backlinks`) imports
`graph_for_candidate()` from the source workspace's existing
`.vault-harness/vault-md-retrieval/vault_md_harness.py` rather than
reimplementing the subprocess call -- reuse, not a hand copy, per this
workspace's own propagation rule. It does not reuse that harness's SQLite
index path at all, so the DO-NOT-BUILD finding about the index's staleness
does not apply here.
"""

from __future__ import annotations

from registry import RegistryError, VaultEntry, load_registry, resolve_vault
from obsidian_backend import ObsidianUnavailable, fetch_backlinks
from security import (PathSecurityError, find_basename_collisions, is_forbidden,
                      is_symlink_under_root, exists_under_root,
                      validate_relative_path)

CONTRACT_VERSION = "vault-backlinks-result-v1"
DEFAULT_MAX_RESULTS = 50


def _error_result(vault_id: str, path: str, message: str, *,
                  review_checks: list[dict] | None = None) -> dict:
    return {
        "contract_version": CONTRACT_VERSION, "vault_id": vault_id, "path": path,
        "backend_used": "none", "backlinks": None, "total": 0,
        "dropped_out_of_scope": 0,
        "review_required": bool(review_checks), "review_checks": review_checks or [],
        "error": message,
    }


def query_backlinks(vault_id: str, path: str, *, max_results: int = DEFAULT_MAX_RESULTS,
                    registry: dict[str, VaultEntry] | None = None) -> dict:
    """The full pipeline: validate -> registry lookup -> CLI call ->
    cross-check every returned path against the vault root -> shape result.
    Never raises for a caller-facing problem -- every failure mode becomes a
    result with backend_used="none" and a specific `error`, per the
    DO-NOT-BUILD ruling's core rule: never turn a failure into a silent
    empty/zero result that reads the same as "confirmed no backlinks"."""
    try:
        clean_path = validate_relative_path(path)
    except PathSecurityError as exc:
        return _error_result(vault_id, path, str(exc))

    if is_forbidden(clean_path):
        return _error_result(vault_id, clean_path,
                             "path matches a forbidden segment (evaluation/gold data "
                             "is never queried or returned by this tool)")

    reg = registry if registry is not None else load_registry()
    try:
        vault = resolve_vault(vault_id, reg)
    except RegistryError as exc:
        return _error_result(vault_id, clean_path, str(exc))

    if not exists_under_root(vault, clean_path):
        return _error_result(
            vault_id, clean_path,
            f"{clean_path!r} does not exist under the registered root for "
            f"vault_id {vault_id!r} -- refusing to query a path this server "
            f"cannot confirm belongs to that vault")

    review_checks = []
    if is_symlink_under_root(vault, clean_path):
        review_checks.append({
            "code": "SYMLINK_TARGET",
            "required_action": ("The queried path is a symlink, not the canonical file. "
                                "Resolve and re-query the canonical path before treating "
                                "backlinks as authoritative for it."),
        })
    collisions = find_basename_collisions(vault, clean_path)
    if collisions:
        review_checks.append({
            "code": "BASENAME_COLLISION",
            "required_action": (f"{len(collisions)} other file(s) under this vault share "
                                f"the basename {clean_path.split('/')[-1]!r}: {collisions}. "
                                f"Confirm any consumer resolves by exact path, not basename."),
        })

    try:
        raw = fetch_backlinks(vault.root, vault.obsidian_vault_name, clean_path)
    except ObsidianUnavailable as exc:
        return _error_result(vault_id, clean_path, f"live backend unavailable: {exc}",
                             review_checks=review_checks or None)

    kept: list[dict] = []
    dropped = 0
    for item in raw:
        # graph_for_candidate()'s own JSON parse falls back to raw text
        # lines (list of str) when the CLI didn't emit valid JSON for this
        # call -- measured 2026-08-08 querying a real vault, not a
        # theoretical case. A bare string carries no link count.
        if isinstance(item, str):
            item = {"file": item}
        elif not isinstance(item, dict):
            dropped += 1
            continue
        source = item.get("file")
        if not isinstance(source, str):
            dropped += 1
            continue
        if is_forbidden(source):
            dropped += 1
            continue
        # The load-bearing check (see obsidian_backend.py's module docstring):
        # `vault=` is not reliably honored, so a CLI answer is only trusted
        # path-by-path, against the vault_id the caller actually asked for.
        if not exists_under_root(vault, source):
            dropped += 1
            continue
        try:
            count = int(item.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        kept.append({"source_path": source, "link_count": count})

    if dropped and not kept:
        review_checks.append({
            "code": "ALL_RESULTS_OUT_OF_SCOPE",
            "required_action": (
                f"obsidian CLI returned {dropped} result(s), none of which exist under "
                f"vault_id {vault_id!r}'s registered root. The CLI's vault= argument is "
                f"not reliably honored (measured 2026-08-08) -- this likely means the "
                f"Obsidian app's active vault does not match vault_id. Re-check which "
                f"vault is open in the Obsidian app before trusting this as 'zero "
                f"backlinks'."),
        })
    elif dropped:
        review_checks.append({
            "code": "SOME_RESULTS_OUT_OF_SCOPE",
            "required_action": (f"{dropped} of {len(raw)} CLI-returned result(s) were "
                                f"dropped because they do not exist under vault_id "
                                f"{vault_id!r}'s registered root."),
        })

    truncated = len(kept) > max_results
    kept = kept[:max_results]

    return {
        "contract_version": CONTRACT_VERSION, "vault_id": vault_id, "path": clean_path,
        "backend_used": "live", "backlinks": kept, "total": len(kept),
        "dropped_out_of_scope": dropped,
        "review_required": bool(review_checks) or truncated,
        "review_checks": review_checks + ([{
            "code": "TRUNCATED",
            "required_action": f"Result truncated to max_results={max_results}; "
                               f"increase max_results if the full set is needed.",
        }] if truncated else []),
        "error": None,
    }
