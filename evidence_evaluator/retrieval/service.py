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
MAX_QUERY_CHARS = 4_000
MAX_READ_LINES = 400
MAX_READ_CHARS = 60_000
MAX_PREVIEW_CHARS = 500


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
        return {"contract_version": READ_CONTRACT, **asdict(result)}

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
