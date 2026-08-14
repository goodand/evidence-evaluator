"""Read-only stdio MCP transport over :mod:`retrieval.service`."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
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
from .service import RetrievalService, ServiceError, compact_search_result


SERVER_INSTRUCTIONS = """Use vault_search as the Markdown entrypoint, inspect its
canonical paths and warnings, then call vault_read before making source claims.
Treat zero hits and exhaustive=false as inconclusive. The server is read-only."""

READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


class McpAuditLog:
    """Append supervisor-visible MCP metadata without source content."""

    def __init__(self, path: Path | None, *, max_calls: int | None = None):
        self.path = path
        self.max_calls = max_calls
        self.calls = 0

    @classmethod
    def from_env(cls) -> "McpAuditLog":
        raw = os.environ.get("EVIDENCE_MCP_AUDIT_LOG")
        max_calls_raw = os.environ.get("EVIDENCE_MCP_MAX_CALLS")
        max_calls = int(max_calls_raw) if max_calls_raw else None
        if max_calls is not None and max_calls < 1:
            raise ValueError("EVIDENCE_MCP_MAX_CALLS must be positive")
        return cls(
            Path(raw).expanduser().resolve() if raw else None,
            max_calls=max_calls,
        )

    def begin(self, tool: str, inputs: dict[str, Any]) -> None:
        self.calls += 1
        if self.max_calls is not None and self.calls > self.max_calls:
            raise ServiceError(
                f"MCP call budget exhausted: {self.calls}>{self.max_calls}"
            )

    def append(self, tool: str, inputs: dict[str, Any], *,
               result: dict[str, Any] | None = None,
               error: BaseException | None = None) -> None:
        if self.path is None:
            return
        record: dict[str, Any] = {
            "contract_version": "evidence-mcp-audit-v1",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": tool,
            "inputs": inputs,
            "outcome": "error" if error else "ok",
        }
        if error is not None:
            record["error"] = {
                "type": type(error).__name__,
                "message": str(error)[:1000],
            }
        elif result is not None:
            record["result"] = _audit_result(tool, result)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
        fd = os.open(self.path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(fd, encoded)
        finally:
            os.close(fd)


def _audit_result(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool == "vault_search":
        return {
            "artifact_digest": result.get("artifact_digest"),
            "retrieved_paths": result.get("retrieved_paths", []),
            "status": result.get("status"),
            "review_required": result.get("review_required"),
        }
    if tool == "vault_read":
        return {
            key: result.get(key)
            for key in (
                "canonical_path", "line_start", "line_end", "content_sha256",
                "document_sha256", "truncated",
            )
        }
    return {
        "path": result.get("path"),
        "backlinks": result.get("backlinks", []),
        "status": result.get("status"),
        "review_required": result.get("review_required"),
    }


def create_mcp(service: RetrievalService, *, audit: McpAuditLog | None = None) -> FastMCP:
    mcp = FastMCP(name="Evidence Vault Retrieval", instructions=SERVER_INSTRUCTIONS)
    search_lock = asyncio.Lock()
    audit = audit or McpAuditLog.from_env()

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
        include_diagnostics: bool = Field(default=False),
    ) -> dict[str, Any]:
        inputs = {
            "query": query,
            "output_k": output_k,
            "candidate_pool_k": candidate_pool_k,
            "graph_seed_k": graph_seed_k,
            "max_turns": max_turns,
            "include_diagnostics": include_diagnostics,
        }
        try:
            audit.begin("vault_search", inputs)
            async with search_lock:
                result = await asyncio.to_thread(
                    service.search,
                    query,
                    output_k=output_k,
                    candidate_pool_k=candidate_pool_k,
                    graph_seed_k=graph_seed_k,
                    max_turns=max_turns,
                )
            audit.append("vault_search", inputs, result=result)
            return result if include_diagnostics else compact_search_result(result)
        except (OSError, ServiceError, ValueError) as exc:
            audit.append("vault_search", inputs, error=exc)
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
        inputs = {"path": path, "line_start": line_start, "line_count": line_count}
        try:
            audit.begin("vault_read", inputs)
            result = await asyncio.to_thread(
                service.read,
                path,
                line_start=line_start,
                line_count=line_count,
            )
            audit.append("vault_read", inputs, result=result)
            return result
        except (OSError, ServiceError, ValueError) as exc:
            audit.append("vault_read", inputs, error=exc)
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
        inputs = {"path": path, "limit": limit}
        try:
            audit.begin("vault_backlinks", inputs)
            result = await asyncio.to_thread(service.backlinks, path, limit=limit)
            audit.append("vault_backlinks", inputs, result=result)
            return result
        except (OSError, ServiceError, ValueError) as exc:
            audit.append("vault_backlinks", inputs, error=exc)
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
