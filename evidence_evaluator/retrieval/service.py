"""Stable in-process search/read service shared by CLI and MCP transports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any

from .corpus import CorpusError, VaultCorpus, query_tokens
from .obsidian import ObsidianCliBackend
from .profile import VaultProfile
from .retriever import RecallFirstRetriever, RetrievalConfig


SEARCH_CONTRACT = "evidence-vault-search-v1"
READ_CONTRACT = "evidence-vault-read-v1"
BACKLINKS_CONTRACT = "evidence-vault-backlinks-v1"
MAX_QUERY_CHARS = 4_000
MAX_READ_LINES = 400
MAX_READ_CHARS = 60_000
MAX_PREVIEW_CHARS = 500

COMPACT_CANDIDATE_KEYS = frozenset({
    "path",
    "canonical_path",
    "authority_class",
    "replica_of",
    "score",
    "rank",
    "preview",
    "preview_line_ranges",
    "preview_truncated",
})


class ServiceError(ValueError):
    """Raised when a transport request violates the service contract."""


class RetrievalService:
    def __init__(
        self,
        profile: VaultProfile,
        *,
        corpus: VaultCorpus | None = None,
        obsidian: ObsidianCliBackend | None = None,
    ):
        self.profile = profile
        self.corpus = corpus or VaultCorpus(profile)
        # Kept on the instance, not only handed to the retriever: `backlinks`
        # needs the same live view the graph walk uses, and re-creating a second
        # backend here would give the two tools different Obsidian state.
        self.obsidian = obsidian
        self.retriever = RecallFirstRetriever(self.corpus, obsidian)

    @classmethod
    def from_profile(cls, profile: VaultProfile) -> "RetrievalService":
        obsidian = ObsidianCliBackend(profile) if profile.obsidian_enabled else None
        return cls(profile, obsidian=obsidian)

    def search(
        self,
        query: str,
        *,
        output_k: int = 8,
        candidate_pool_k: int = 50,
        graph_seed_k: int = 12,
        max_turns: int = 6,
    ) -> dict[str, Any]:
        if not query.strip() or len(query) > MAX_QUERY_CHARS:
            raise ServiceError(f"Query length must be 1..{MAX_QUERY_CHARS}")
        artifact = self.retriever.retrieve(
            query,
            RetrievalConfig(
                output_k=output_k,
                candidate_pool_k=candidate_pool_k,
                graph_seed_k=graph_seed_k,
                max_turns=max_turns,
            ),
        )
        candidates = []
        for candidate in artifact["candidates"]:
            document = self.corpus.documents[candidate["canonical_path"]]
            preview, ranges, truncated = _preview(document.body, query)
            candidates.append(
                {
                    **candidate,
                    "preview": preview,
                    "preview_line_ranges": ranges,
                    "preview_truncated": truncated,
                }
            )

        # `exhaustive=false` is an inconclusive retrieval result even when it
        # contains useful candidates. A caller must read and assess evidence;
        # no transport may relabel that state as a complete absence decision.
        review_required = not artifact["exhaustive"] or bool(artifact["warnings"])
        result: dict[str, Any] = {
            "contract_version": SEARCH_CONTRACT,
            "status": "review_required" if review_required else "complete",
            "review_required": review_required,
            "exhaustive": artifact["exhaustive"],
            "terminal_reason": artifact["terminal_reason"],
            "warnings": artifact["warnings"],
            "retrieved_paths": artifact["retrieved_paths"],
            "candidate_pool": artifact["candidate_pool"],
            "discovered_path_count": artifact["discovered_path_count"],
            "candidates": candidates,
            "turns": artifact["turns"],
            "next_action": (
                "Read selected canonical paths; treat zero hits or a budget stop as inconclusive."
            ),
        }
        # v0.1 contract field, derived here rather than inside the retriever:
        # the public API is what stabilises, the algorithm stays replaceable.
        # `None` means "no fallback was needed" -- so it must not be None when
        # one WAS used, or the field cannot distinguish the two cases.
        result["fallback_used"] = _fallback_from_warnings(result.get("warnings"))
        if result["fallback_used"]:
            result["review_required"] = True
        result["artifact_digest"] = _digest(result)
        return result

    def read(
        self,
        path: str,
        *,
        line_start: int = 1,
        line_count: int = 200,
    ) -> dict[str, Any]:
        if line_count > MAX_READ_LINES:
            raise ServiceError(f"line_count must not exceed {MAX_READ_LINES}")
        try:
            result = self.corpus.read_range(path, line_start, line_count)
        except CorpusError as exc:
            raise ServiceError(str(exc)) from exc
        if len(result.content) > MAX_READ_CHARS:
            raise ServiceError(f"Read content exceeds {MAX_READ_CHARS} characters")
        out = {"contract_version": READ_CONTRACT, **asdict(result)}
        out.setdefault("fallback_used", None)
        return out

    def backlinks(self, path: str, *, limit: int = 20) -> dict[str, Any]:
        """Which documents link HERE. The third v0.1 tool.

        NOT a new algorithm. The graph walk already computed backlinks
        internally (`corpus.backlinks` plus the Obsidian CLI's live view); an
        agent simply could not ASK for them. This is a thin exposure over the
        pieces that were already there, which is why it reuses
        `corpus.canonicalize` for the security boundary rather than growing a
        second copy of it -- a second copy is a copy that can drift.

        ERROR TOLERANCE. If the Obsidian CLI is unavailable the call does NOT
        fail: it returns the filesystem graph, says `fallback_used:
        "filesystem"`, and reports `status: "partial"` with the warning. A
        degraded answer that says it is degraded is more useful than a refusal,
        and far more useful than a silent empty list.

        FAIL-CLOSED, though, on the security boundary: outside the vault, a
        blocked part (`hidden_gold`, `private_eval`, ...), a symlink escape or a
        non-Markdown path is refused outright. Those are not partial results.
        """
        if limit < 1:
            raise ServiceError("limit must be >= 1")
        canonical = self.corpus.canonicalize(path)
        if canonical is None:
            raise ServiceError(
                f"refusing backlinks for {path!r}: not a canonical Markdown path "
                "inside this vault, or it is on the blocked list")

        warnings: list[str] = list(self.corpus.warnings)
        # A symlink is never content authority (symlink-vs-moc-2026-07-30,
        # adopted hybrid #6) -- `canonicalize` already resolved it silently.
        # Surface that resolution happened, without changing the answer.
        if self.corpus.is_symlink_alias(path):
            warnings.append(
                f"Queried path {path!r} is a symlink; resolved to canonical "
                f"path {canonical.relative!r}."
            )
        fallback_used: str | None = None
        found = list(self.corpus.backlinks(canonical.relative))

        if self.obsidian is not None:
            live = self.obsidian.neighbors(canonical)
            warnings.extend(live.warnings)
            if live.available:
                for raw in live.backlinks:
                    resolved = self.corpus.canonicalize(raw)
                    if resolved is not None and resolved.relative not in found:
                        found.append(resolved.relative)
            else:
                # The CLI is the preferred source; losing it is a degradation,
                # not a failure. Name it so a caller can tell the two apart.
                fallback_used = "filesystem"
        else:
            fallback_used = "filesystem"

        found.sort()
        truncated = len(found) > limit
        status = "partial" if (fallback_used or warnings) else "ok"
        return {
            "contract_version": BACKLINKS_CONTRACT,
            "status": status,
            "path": canonical.relative,
            "backlinks": found[:limit],
            "limit": limit,
            "truncated": truncated,
            "discovered_path_count": len(found),
            "warnings": list(dict.fromkeys(warnings)),
            "fallback_used": fallback_used,
            "review_required": bool(fallback_used or warnings or not found),
            "exhaustive": not truncated and fallback_used is None,
            "terminal_reason": ("graph-provider-partially-unavailable"
                               if fallback_used else "complete"),
            "next_action": (
                "Read a backlink to find the entry point that cites this "
                "document; zero backlinks is not evidence that none exist when "
                "review_required is true."),
        }

    def policy(self) -> dict[str, Any]:
        return {
            "contract_version": "evidence-vault-policy-v1",
            "read_only": True,
            "network_required": False,
            "search_policy": "recall-first",
            "vault_root": str(self.profile.root),
            "vault_name": self.profile.vault_name,
            "blocked_parts": sorted(self.profile.blocked_parts),
            "limits": {
                "max_query_chars": MAX_QUERY_CHARS,
                "max_read_lines": MAX_READ_LINES,
                "max_read_chars": MAX_READ_CHARS,
                "max_markdown_bytes": self.profile.max_markdown_bytes,
            },
        }


def compact_search_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return the bounded agent-facing projection of a search artifact.

    The full candidate pool and turn-by-turn graph diagnostics are useful for
    evaluator development, but exposing them to every MCP caller caused one
    three-result search to consume roughly 280k input tokens. The artifact
    digest still identifies the full in-process result.
    """
    compact = {
        key: value
        for key, value in result.items()
        if key not in {"candidate_pool", "turns", "candidates"}
    }
    compact["candidates"] = [
        {key: value for key, value in candidate.items()
         if key in COMPACT_CANDIDATE_KEYS}
        for candidate in result.get("candidates", [])
    ]
    warnings = [str(item) for item in result.get("warnings", [])]
    compact["warning_count"] = len(warnings)
    compact["warnings"] = _compact_warnings(warnings)
    compact["projection"] = "compact-v1"
    compact["diagnostics_omitted"] = ["candidate_pool", "turns"]
    return compact


def _compact_warnings(warnings: list[str]) -> list[str]:
    obsidian = [item for item in warnings if "obsidian" in item.casefold()]
    other = list(dict.fromkeys(item for item in warnings if item not in obsidian))
    compact = [item[:300] for item in other[:5]]
    if obsidian:
        compact.append(
            f"Obsidian CLI graph probes unavailable or failed: {len(obsidian)}; "
            "filesystem fallback used."
        )
    if len(other) > 5:
        compact.append(f"Additional non-Obsidian warnings omitted: {len(other) - 5}.")
    return compact


def _fallback_from_warnings(warnings: Any) -> str | None:
    """Which degraded source produced this answer, or None.

    Read off the warnings the providers already emit, so adding a provider does
    not require touching the retriever. A warning naming the Obsidian CLI means
    the filesystem graph carried the run.
    """
    for warning in (warnings or []):
        low = str(warning).lower()
        if "obsidian" in low and ("unavailable" in low or "failed" in low
                                  or "not found" in low or "timeout" in low):
            return "filesystem"
    return None


def _preview(body: str, query: str) -> tuple[str, list[str], bool]:
    lines = body.splitlines()
    terms = query_tokens(query)
    best = 0
    best_score = -1
    for index, line in enumerate(lines):
        folded = line.casefold()
        score = sum(term in folded for term in terms)
        if score > best_score:
            best = index
            best_score = score
    start = max(0, best - 2)
    end = min(len(lines), start + 8)
    content = "\n".join(lines[start:end])
    clipped = content[:MAX_PREVIEW_CHARS]
    return clipped, [f"{start + 1}-{max(start + 1, end)}"], len(clipped) < len(content)


def _digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
