"""Read-only stdio MCP transport over :mod:`retrieval.service`."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from .profile import VaultProfile
from .retriever import (
    MAX_CANDIDATE_POOL_K,
    MAX_GRAPH_SEED_K,
    MAX_OUTPUT_K,
    MAX_TURNS,
)
from .service import RetrievalService, ServiceError


SERVER_INSTRUCTIONS = """Use vault_search as the Markdown entrypoint, inspect its
canonical paths and warnings, then call vault_read before making source claims.
Treat zero hits and exhaustive=false as inconclusive. The server is read-only."""

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def create_mcp(service: RetrievalService) -> FastMCP:
    mcp = FastMCP(name="Evidence Vault Retrieval", instructions=SERVER_INSTRUCTIONS)
    search_lock = asyncio.Lock()

    @mcp.tool(
        name="vault_search",
        description=(
            "Recall-first Markdown search using lexical ranking, filesystem links, "
            "and optional Obsidian backlinks. Never writes to the vault."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def vault_search(
        query: str = Field(min_length=1, max_length=4000),
        output_k: int = Field(default=8, ge=1, le=MAX_OUTPUT_K),
        candidate_pool_k: int = Field(
            default=50, ge=1, le=MAX_CANDIDATE_POOL_K
        ),
        graph_seed_k: int = Field(default=12, ge=1, le=MAX_GRAPH_SEED_K),
        max_turns: int = Field(default=6, ge=1, le=MAX_TURNS),
    ) -> dict[str, Any]:
        try:
            async with search_lock:
                return await asyncio.to_thread(
                    service.search,
                    query,
                    output_k=output_k,
                    candidate_pool_k=candidate_pool_k,
                    graph_seed_k=graph_seed_k,
                    max_turns=max_turns,
                )
        except (OSError, ServiceError, ValueError) as exc:
            raise ToolError(f"Vault search failed: {exc}") from exc

    @mcp.tool(
        name="vault_read",
        description=(
            "Read one bounded range from a canonical vault-relative Markdown path."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def vault_read(
        path: str = Field(min_length=1, max_length=4096),
        line_start: int = Field(default=1, ge=1),
        line_count: int = Field(default=200, ge=1, le=400),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(
                service.read,
                path,
                line_start=line_start,
                line_count=line_count,
            )
        except (OSError, ServiceError, ValueError) as exc:
            raise ToolError(f"Vault read failed: {exc}") from exc

    @mcp.tool(
        name="vault_backlinks",
        description=(
            "Which vault documents link to this path. Uses the Obsidian CLI when "
            "it answers and the filesystem graph when it does not -- a CLI "
            "failure degrades the answer and says so (`fallback_used`), it does "
            "not disable the tool. Zero backlinks with review_required=true is "
            "not evidence that none exist."
        ),
        annotations=READ_ONLY,
        structured_output=True,
    )
    async def vault_backlinks(
        path: str = Field(min_length=1, max_length=4096),
        limit: int = Field(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        try:
            return await asyncio.to_thread(service.backlinks, path, limit=limit)
        except (OSError, ServiceError, ValueError) as exc:
            raise ToolError(f"Vault backlinks failed: {exc}") from exc

    @mcp.resource(
        "vault://retrieval/policy",
        name="Vault retrieval policy",
        description="Machine-readable runtime policy and limits.",
        mime_type="application/json",
    )
    def retrieval_policy() -> str:
        return json.dumps(service.policy(), ensure_ascii=False, sort_keys=True)

    return mcp


def main() -> None:
    service = RetrievalService.from_profile(VaultProfile.from_env())
    create_mcp(service).run(transport="stdio")


if __name__ == "__main__":
    main()
