from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

from evidence_evaluator.retrieval.cli import main as cli_main
from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.service import RetrievalService, compact_search_result


@pytest.fixture()
def transport_vault(tmp_path: Path) -> Path:
    (tmp_path / "HANDOFF.md").write_text(
        "# Handoff\n\nneedle entry links to [[AUTHORITY]].\n", encoding="utf-8"
    )
    (tmp_path / "AUTHORITY.md").write_text(
        "# Authority\n\nCanonical next action is review.\n", encoding="utf-8"
    )
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "hidden_gold" / "gold.md").write_text(
        "needle secret", encoding="utf-8"
    )
    return tmp_path


def test_cli_and_service_return_same_canonical_candidates(
    transport_vault: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    expected = RetrievalService(
        VaultProfile(root=transport_vault, obsidian_enabled=False)
    ).search(
        "needle entry",
        output_k=2,
        candidate_pool_k=4,
        graph_seed_k=2,
        max_turns=3,
    )
    exit_code = cli_main(
        [
            "--root",
            str(transport_vault),
            "--no-obsidian",
            "search",
            "needle entry",
            "--output-k",
            "2",
            "--candidate-pool-k",
            "4",
            "--graph-seed-k",
            "2",
            "--max-turns",
            "3",
        ]
    )
    actual = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert [item["path"] for item in actual["candidates"]] == [
        item["path"] for item in expected["candidates"]
    ]
    assert actual["retrieved_paths"] == expected["retrieved_paths"]


def test_compact_projection_collapses_repeated_provider_warnings() -> None:
    result = {
        "candidates": [],
        "warnings": [
            "Obsidian backlinks unavailable for a.md",
            "Obsidian links unavailable for b.md",
            "Ignored symlink directory: linked",
        ],
        "candidate_pool": ["a.md"],
        "turns": [{"large": "diagnostic"}],
    }
    compact = compact_search_result(result)
    assert compact["warning_count"] == 3
    assert compact["warnings"] == [
        "Ignored symlink directory: linked",
        "Obsidian CLI graph probes unavailable or failed: 2; filesystem fallback used.",
    ]
    assert "candidate_pool" not in compact
    assert "turns" not in compact


def test_cli_read_rejects_private_material(
    transport_vault: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = cli_main(
        [
            "--root",
            str(transport_vault),
            "--no-obsidian",
            "read",
            "hidden_gold/gold.md",
        ]
    )
    assert exit_code == 2
    assert "Unsafe Markdown path" in json.loads(capsys.readouterr().err)["error"]


async def _mcp_smoke(vault: Path) -> None:
    mcp = pytest.importorskip("mcp")
    del mcp
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env.update(
        {
            "EVIDENCE_VAULT_ROOT": str(vault),
            "EVIDENCE_OBSIDIAN_ENABLED": "0",
            "EVIDENCE_MCP_AUDIT_LOG": str(vault.parent / "mcp-audit.jsonl"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "evidence_evaluator.retrieval.mcp_server"],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            tools = {tool.name: tool for tool in listed.tools}
            # v0.1 (2026-08-12) added the third tool. `vault_backlinks` exposes
            # the graph the walk already used internally; see
            # docs/PLAN_V01_AUDIT_AND_GAPS.md and tests/test_v01_tool_contract.py.
            assert set(tools) == {"vault_search", "vault_read", "vault_backlinks"}
            assert tools["vault_search"].annotations.readOnlyHint is True
            assert tools["vault_search"].annotations.openWorldHint is False
            assert tools["vault_search"].inputSchema["properties"]["output_k"][
                "maximum"
            ] == 500

            result = await session.call_tool(
                "vault_search",
                {
                    "query": "needle entry",
                    "output_k": 2,
                    "candidate_pool_k": 4,
                    "graph_seed_k": 2,
                    "max_turns": 3,
                },
            )
            assert result.isError is False
            assert result.structuredContent["contract_version"] == (
                "evidence-vault-search-v1"
            )
            assert "AUTHORITY.md" in result.structuredContent["retrieved_paths"]
            assert result.structuredContent["projection"] == "compact-v1"
            assert "candidate_pool" not in result.structuredContent
            assert "turns" not in result.structuredContent

            full = await session.call_tool(
                "vault_search",
                {
                    "query": "needle entry",
                    "output_k": 2,
                    "candidate_pool_k": 4,
                    "graph_seed_k": 2,
                    "max_turns": 3,
                    "include_diagnostics": True,
                },
            )
            assert "candidate_pool" in full.structuredContent
            assert "turns" in full.structuredContent

            read = await session.call_tool(
                "vault_read", {"path": "AUTHORITY.md", "line_count": 2}
            )
            assert read.isError is False

            blocked = await session.call_tool(
                "vault_read", {"path": "hidden_gold/gold.md"}
            )
            assert blocked.isError is True

            resources = await session.list_resources()
            assert [str(item.uri) for item in resources.resources] == [
                "vault://retrieval/policy"
            ]

    records = [
        json.loads(line)
        for line in (vault.parent / "mcp-audit.jsonl").read_text(
            encoding="utf-8"
        ).splitlines()
    ]
    assert [record["tool"] for record in records] == [
        "vault_search", "vault_search", "vault_read", "vault_read"
    ]
    successful_read = records[2]
    assert successful_read["result"]["canonical_path"] == "AUTHORITY.md"
    assert len(successful_read["result"]["content_sha256"]) == 64
    assert '"content":' not in json.dumps(records, ensure_ascii=False)
    assert records[3]["outcome"] == "error"


def test_stdio_mcp_uses_the_same_read_only_service(transport_vault: Path) -> None:
    asyncio.run(_mcp_smoke(transport_vault))
