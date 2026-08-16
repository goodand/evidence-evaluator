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

import os

from registry import RegistryError, VaultEntry, load_registry, resolve_vault
from security import (DEFAULT_FORBIDDEN_SEGMENTS, PathSecurityError,
                      find_basename_collisions, is_forbidden,
                      is_forbidden_resolved, is_symlink_under_root,
                      exists_under_root, validate_relative_path)

# Backend selection for the CLI-transport layer only -- registry/security
# above are unchanged either way. Default stays "harness" (current, tested
# behavior); "evidence" opts into the evidence-evaluator-backed adapter,
# which has a measured gap (see obsidian_backend_evidence.py's module
# docstring: link counts default to 1, not the real per-file count) and is
# not yet the default for that reason.
BACKLINKS_BACKEND = os.environ.get("VAULT_BACKLINKS_BACKEND", "harness")
if BACKLINKS_BACKEND == "evidence":
    from obsidian_backend_evidence import (ObsidianUnavailable, confirm_active_vault,
                                           fetch_backlinks)
elif BACKLINKS_BACKEND == "harness":
    from obsidian_backend import ObsidianUnavailable, confirm_active_vault, fetch_backlinks
else:
    raise ValueError(
        f"VAULT_BACKLINKS_BACKEND must be 'harness' or 'evidence', got {BACKLINKS_BACKEND!r}")

# Independent of which live backend is selected above: when the live CLI is
# unavailable, fall back to evidence-evaluator's broader filesystem scan
# rather than failing outright -- ALWAYS labeled as degraded (see
# filesystem_fallback_backlinks's own docstring for why this is not a
# live-equivalent answer: 50 vs 5 real entries for the same query, measured
# 2026-08-15). On by default per an explicit 2026-08-15 decision, made after
# that exact tradeoff was measured and shown: prefer a clearly-labeled,
# broader answer over an outright failure. Set
# VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0 to go back to pure live-only,
# no-fallback behavior (the original DO-NOT-BUILD-derived contract).
#
# An allowlist of "off" spellings, not a blocklist of "on" ones: an
# adversarial review (2026-08-15) found the earlier `not in {"0", "false",
# "False"}` form would silently treat a typo'd or unexpected value (e.g.
# "disabled", "No", a stray "TRUE\n") as enabled -- surprising for a switch
# whose whole point is opting out. Any value not explicitly recognized as
# "off" here still means "on" (the default), but the false-spellings list is
# now deliberately wide rather than three exact strings.
# Compared case-insensitively: an earlier version listed exact spellings, so
# "FALSE"/"OFF"/"NO" (uppercase) fell through and silently ENABLED the very
# thing the operator was trying to turn off (adversarial review 2026-08-16).
_FALLBACK_OFF_VALUES = {"0", "false", "no", "off", "disabled"}
FILESYSTEM_FALLBACK_ENABLED = (
    os.environ.get("VAULT_BACKLINKS_FILESYSTEM_FALLBACK", "1").strip().casefold()
    not in _FALLBACK_OFF_VALUES
)
if FILESYSTEM_FALLBACK_ENABLED:
    from obsidian_backend_evidence import filesystem_fallback_backlinks
else:
    filesystem_fallback_backlinks = None

# v2 (2026-08-10): `total`'s meaning changed from "length of the returned
# (possibly truncated) list" to "real count before truncation", and a new
# `returned_count` field was added -- a breaking change for any consumer
# that assumed total == len(backlinks). Reproduced 2026-08-10 (independent
# review round 2, finding #2): the v1 semantic bug (total computed after
# truncation) was fixed without bumping the version, so a caller pinned to
# v1 could not detect that `total` now means something different.
CONTRACT_VERSION = "vault-backlinks-result-v2"
DEFAULT_MAX_RESULTS = 50
MAX_RESULTS_UPPER_BOUND = 1000


def _error_result(vault_id: str, path: str, message: str, *,
                  review_checks: list[dict] | None = None) -> dict:
    return {
        "contract_version": CONTRACT_VERSION, "vault_id": vault_id, "path": path,
        "backend_used": "none", "backlinks": None, "total": 0, "returned_count": 0,
        "dropped_out_of_scope": 0,
        "dropped_by_reason": {"malformed": 0, "forbidden": 0, "out_of_scope": 0},
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
    # `max_results` must be validated, not trusted -- reproduced 2026-08-09
    # (independent review of the .vault-harness reuse contract, finding #3):
    # a negative value (`-1`) was never rejected and silently returned a
    # Python-slice-semantics result (`kept[:-1]`, i.e. "all but the last
    # item") instead of an error or an empty list.
    if (not isinstance(max_results, int) or isinstance(max_results, bool)
            or not (1 <= max_results <= MAX_RESULTS_UPPER_BOUND)):
        return _error_result(
            vault_id, path,
            f"max_results must be an integer in [1, {MAX_RESULTS_UPPER_BOUND}], "
            f"got {max_results!r}")
    try:
        clean_path = validate_relative_path(path)
    except PathSecurityError as exc:
        return _error_result(vault_id, path, str(exc))

    if is_forbidden(clean_path):
        return _error_result(vault_id, clean_path,
                             f"path matches a forbidden segment "
                             f"({', '.join(DEFAULT_FORBIDDEN_SEGMENTS)} are never queried "
                             f"or returned by this tool)")

    # `load_registry()` itself can raise RegistryError (malformed registry
    # file), not just `resolve_vault()` (unknown vault_id in an otherwise
    # valid registry). It used to be called outside this try block, so a
    # malformed registry escaped as an uncaught exception at the MCP
    # boundary instead of the structured `backend_used: "none"` result every
    # other failure mode gets. Reproduced 2026-08-10 (independent review
    # round 2, finding #1): a registry with a non-object vault entry crashed
    # query_backlinks() itself, not just load_registry().
    try:
        reg = registry if registry is not None else load_registry()
        vault = resolve_vault(vault_id, reg)
    except RegistryError as exc:
        return _error_result(vault_id, clean_path, str(exc))

    # Re-check against the RESOLVED path now that we have a vault. The
    # literal check above cannot see through a symlink alias
    # (`alias/gold.json` where `alias -> hidden_gold`) -- reproduced
    # 2026-08-09, adversarial review findings #2/#4, where such a path
    # cleared both the literal check and exists_under_root and reached the
    # external CLI.
    if is_forbidden_resolved(vault, clean_path):
        return _error_result(vault_id, clean_path,
                             f"path resolves inside a forbidden segment "
                             f"({', '.join(DEFAULT_FORBIDDEN_SEGMENTS)} are never queried "
                             f"or returned by this tool)")

    if not exists_under_root(vault, clean_path):
        return _error_result(
            vault_id, clean_path,
            f"{clean_path!r} does not exist under the registered root for "
            f"vault_id {vault_id!r} -- refusing to query a path this server "
            f"cannot confirm belongs to that vault")

    review_checks = []
    # FUNDAMENTAL LIMITATION (independent review round 2, finding #3, not
    # fully closable): `exists_under_root` only proves the queried path
    # exists somewhere under vault_id's own filesystem root -- it cannot
    # prove Obsidian actually answered FROM this vault rather than another
    # one with an overlapping relative-path layout (e.g. two vaults that
    # both have `notes/a.md` with different content). No Obsidian CLI
    # command exposes "which vault is currently active" (checked 2026-08-10:
    # `obsidian vaults verbose` lists all registered vaults with no active
    # marker), so there is no available identity check beyond path
    # existence. This does not detect a wrong-vault answer -- it only
    # refuses to stay silent about the specific condition (the queried path
    # existing in more than one registered vault) where that failure mode
    # cannot be ruled out.
    same_path_elsewhere = sorted(
        other_id for other_id, other_vault in reg.items()
        if other_id != vault_id and exists_under_root(other_vault, clean_path))
    if same_path_elsewhere:
        review_checks.append({
            "code": "AMBIGUOUS_ACROSS_REGISTERED_VAULTS",
            "required_action": (
                f"{clean_path!r} also exists under registered vault(s) "
                f"{same_path_elsewhere}. This tool cannot prove the CLI answered "
                f"from vault_id {vault_id!r} specifically rather than one of "
                f"these -- confirm independently (e.g. by content) before "
                f"trusting this result as authoritative for {vault_id!r}."),
        })
    if is_symlink_under_root(vault, clean_path):
        review_checks.append({
            "code": "SYMLINK_TARGET",
            "required_action": (
                "The queried path is a symlink, not the canonical file. Obsidian does "
                "not index symlinked paths (measured 2026-08-08 across all registered "
                "vaults: 18/18 sampled symlinks unresolvable, for backlinks/links/tags/"
                "wordcount alike), so a zero or failed result here says nothing about "
                "the note itself. Re-query the canonical path -- e.g. the target of "
                "this symlink -- before drawing any conclusion."),
        })
    collisions = find_basename_collisions(vault, clean_path)
    if collisions:
        review_checks.append({
            "code": "BASENAME_COLLISION",
            "required_action": (f"{len(collisions)} other file(s) under this vault share "
                                f"the basename {clean_path.split('/')[-1]!r}: {collisions}. "
                                f"Confirm any consumer resolves by exact path, not basename."),
        })

    # Best-effort cross-check for the AMBIGUOUS_ACROSS_REGISTERED_VAULTS
    # limitation above: a second, independent CLI subcommand called with the
    # same cwd. Not proof (both share the same cwd-resolution mechanism),
    # but a real disagreement between them is a strong signal, and honest
    # "unknown" is reported rather than assumed "confirmed" on any failure.
    active_vault_status = confirm_active_vault(vault.root)
    if active_vault_status == "mismatch":
        review_checks.append({
            "code": "ACTIVE_VAULT_MISMATCH",
            "required_action": (
                f"'obsidian vault info=path' (same cwd as the backlinks call) "
                f"reported a DIFFERENT vault than vault_id {vault_id!r}'s "
                f"registered root. Do not trust `total`/`backlinks` from this "
                f"call -- it likely answered from the wrong vault."),
        })
    elif active_vault_status == "unknown":
        review_checks.append({
            "code": "ACTIVE_VAULT_UNKNOWN",
            "required_action": (
                "Could not independently confirm which vault the Obsidian CLI "
                "is answering from ('obsidian vault info=path' failed or is "
                "unavailable). This is not a fetch failure by itself, but the "
                "AMBIGUOUS_ACROSS_REGISTERED_VAULTS risk above cannot be ruled "
                "out for this call."),
        })

    backend_used = "live"
    try:
        raw = fetch_backlinks(vault.root, vault.obsidian_vault_name, clean_path)
    except ObsidianUnavailable as exc:
        # The fallback gets its OWN guard, not the live call's. Reproduced
        # 2026-08-15 (adversarial review, blocker): this call was unguarded,
        # so a vault root deleted or made unreadable between `load_registry()`
        # and here raised OSError/ProfileError straight out of
        # `query_backlinks()` -- breaking this module's whole promise that
        # every caller-facing problem becomes a structured result with
        # `backend_used: "none"` and an `error` string, never a raw exception
        # at the MCP boundary. A fallback that crashes is strictly worse than
        # the honest failure it was added to avoid.
        fallback_paths = None
        fallback_error = None
        if FILESYSTEM_FALLBACK_ENABLED and filesystem_fallback_backlinks is not None:
            try:
                fallback_paths = filesystem_fallback_backlinks(vault.root, clean_path)
            except Exception as fallback_exc:  # noqa: BLE001 -- see above
                fallback_error = fallback_exc
        if fallback_paths is None:
            if fallback_error is not None:
                return _error_result(
                    vault_id, clean_path,
                    f"live backend unavailable: {exc}; filesystem fallback also "
                    f"failed: {fallback_error!r}",
                    review_checks=review_checks or None)
            return _error_result(vault_id, clean_path, f"live backend unavailable: {exc}",
                                 review_checks=review_checks or None)
        raw = [{"file": item} for item in fallback_paths]
        backend_used = "filesystem_fallback"
        review_checks.append({
            "code": "FILESYSTEM_FALLBACK_USED",
            "required_action": (
                f"Live Obsidian CLI was unavailable ({exc}); this result came from "
                f"a broader filesystem scan instead, not a live answer. That scan "
                f"counts a filename mention inside a code span or wikilink the same "
                f"as a real indexed link -- it can return substantially MORE entries "
                f"than a live answer would (measured 2026-08-15: 50 vs 5 for the "
                f"same real query). Treat `backlinks`/`total` here as lower-precision "
                f"evidence, not a live-equivalent count."),
        })

    kept: list[dict] = []
    # Counted per reason, not lumped together. A single `dropped` total made
    # the review_check below misattribute every drop to a vault mismatch --
    # reproduced 2026-08-09 (adversarial review findings #1/#6): a malformed
    # entry, or one correctly rejected by the forbidden-segment filter,
    # still produced "none of which exist under the registered root ...
    # the Obsidian app's active vault does not match vault_id", sending the
    # reader after the wrong cause.
    drops = {"malformed": 0, "forbidden": 0, "out_of_scope": 0}
    for item in raw:
        # graph_for_candidate()'s own JSON parse falls back to raw text
        # lines (list of str) when the CLI didn't emit valid JSON for this
        # call -- measured 2026-08-08 querying a real vault, not a
        # theoretical case. A bare string carries no link count.
        if isinstance(item, str):
            item = {"file": item}
        elif not isinstance(item, dict):
            drops["malformed"] += 1
            continue
        source = item.get("file")
        if not isinstance(source, str):
            drops["malformed"] += 1
            continue
        if is_forbidden(source) or is_forbidden_resolved(vault, source):
            drops["forbidden"] += 1
            continue
        # The load-bearing check (see obsidian_backend.py's module docstring):
        # `vault=` is not reliably honored, so a CLI answer is only trusted
        # path-by-path, against the vault_id the caller actually asked for.
        if not exists_under_root(vault, source):
            drops["out_of_scope"] += 1
            continue
        try:
            count = int(item.get("count", 1))
        except (TypeError, ValueError):
            count = 1
        kept.append({"source_path": source, "link_count": count})

    dropped = sum(drops.values())
    breakdown = ", ".join(f"{n} {reason}" for reason, n in drops.items() if n)

    if drops["out_of_scope"] and not kept:
        review_checks.append({
            "code": "ALL_RESULTS_OUT_OF_SCOPE",
            "required_action": (
                f"obsidian CLI returned {len(raw)} result(s) and none survived filtering "
                f"({breakdown}); at least one failed the vault-root check for vault_id "
                f"{vault_id!r}. The CLI's vault= argument is not reliably honored "
                f"(measured 2026-08-08) -- this may mean the Obsidian app's active vault "
                f"does not match vault_id. Re-check which vault is open in the Obsidian "
                f"app before trusting this as 'zero backlinks'."),
        })
    elif drops["out_of_scope"]:
        review_checks.append({
            "code": "SOME_RESULTS_OUT_OF_SCOPE",
            "required_action": (f"{drops['out_of_scope']} of {len(raw)} CLI-returned "
                                f"result(s) were dropped because they do not exist under "
                                f"vault_id {vault_id!r}'s registered root."),
        })
    elif dropped and not kept:
        # Everything was dropped, but NOT for the vault-mismatch reason --
        # say so instead of steering the reader toward the wrong hypothesis.
        review_checks.append({
            "code": "ALL_RESULTS_FILTERED",
            "required_action": (
                f"obsidian CLI returned {len(raw)} result(s) and none survived filtering "
                f"({breakdown}). This is not a vault-scope problem: no result failed the "
                f"vault-root check. 'forbidden' means the filter excluded protected "
                f"paths (working as intended); 'malformed' means the CLI's output did "
                f"not parse as expected for those entries."),
        })
    elif dropped:
        review_checks.append({
            "code": "SOME_RESULTS_FILTERED",
            "required_action": (f"{dropped} of {len(raw)} CLI-returned result(s) were "
                                f"dropped ({breakdown}). None failed the vault-root "
                                f"check."),
        })

    # `total` must be the real count BEFORE truncation. Reproduced 2026-08-09
    # (independent review of the .vault-harness reuse contract, finding #3):
    # this used to slice `kept` first and then report `len(kept)` as `total`,
    # so 2 real results with `max_results=1` reported `total=1` -- a caller
    # reading only `total` had no way to tell "there is exactly one backlink"
    # from "there are more, but you only asked to see one".
    total_available = len(kept)
    truncated = total_available > max_results
    returned = kept[:max_results]

    return {
        "contract_version": CONTRACT_VERSION, "vault_id": vault_id, "path": clean_path,
        "backend_used": backend_used, "backlinks": returned, "total": total_available,
        "returned_count": len(returned),
        # `dropped_out_of_scope` now means exactly what it says -- only the
        # vault-root failures. `dropped_by_reason` carries the full picture
        # so a caller can tell a security filter doing its job apart from a
        # wrong-vault answer (findings #1/#6).
        "dropped_out_of_scope": drops["out_of_scope"],
        "dropped_by_reason": dict(drops),
        "review_required": bool(review_checks) or truncated,
        "review_checks": review_checks + ([{
            "code": "TRUNCATED",
            "required_action": f"Result truncated to max_results={max_results}; "
                               f"increase max_results if the full set is needed.",
        }] if truncated else []),
        "error": None,
    }
