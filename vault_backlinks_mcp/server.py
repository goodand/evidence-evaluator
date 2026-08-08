#!/usr/bin/env python3
"""stdio MCP server exposing exactly one tool: `vault_backlinks`.

Diagnostic complement to the existing `vault_search` MCP tool
(`.vault-harness/vault-md-retrieval/vault_retrieval_mcp_server.py` in the
source workspace, not reimplemented or replaced here). `vault_search` is a
question-driven automatic graph walk; `vault_backlinks` is a single exact-path
"what links here, right now" check -- see the design proposal's closing
principle (`DESIGN_PROPOSAL_vault_backlinks_mcp_server_20260807.md` §9) for
why the two are complementary, not duplicate, tools.

Run directly: `python3 server.py` (stdio transport). Requires `fastmcp`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastmcp import FastMCP

from contracts import DEFAULT_MAX_RESULTS, query_backlinks

mcp = FastMCP("Vault Backlinks")


@mcp.tool(name="vault_backlinks", annotations={"readOnlyHint": True})
def vault_backlinks(vault_id: str, path: str,
                    max_results: int = DEFAULT_MAX_RESULTS) -> dict:
    """Exact-path incoming-link lookup for one file in a registered vault.

    Live-only: answers come from the Obsidian CLI at call time, never from a
    cached index (see contracts.py's module docstring for why). A failure
    (Obsidian unavailable, IPC pointed at the wrong vault, path not found)
    is always reported as `error` with `backend_used: "none"` -- never
    silently converted to an empty backlink list. Read `review_required` and
    `review_checks` before treating a result as final; a non-empty
    `review_checks` means something needs a human or a follow-up check, not
    that the call failed. A review check does not by itself mean
    `backlink_count` is wrong or uncertain -- each check has its own scope
    (stated in its `required_action`), which may be unrelated to whether the
    count for this exact path is correct. When `error` is null and
    `backend_used` is `"live"`, `backlink_count` is a real count from this
    call; do not downgrade your confidence in it just because
    `review_checks` is non-empty -- check whether that specific entry's
    scope actually bears on the count before treating the count as uncertain.
    """
    return query_backlinks(vault_id, path, max_results=max_results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
