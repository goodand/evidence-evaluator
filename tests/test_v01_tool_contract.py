"""v0.1 tool contract — verified in a real stdio MCP process.

Audited 2026-08-12 (docs/PLAN_V01_AUDIT_AND_GAPS.md). Two things blocked v0.1:

  * `vault_backlinks` was not exposed. The CAPABILITY was already there and used
    inside the graph walk (`corpus.backlinks`, the Obsidian CLI's live view) --
    an agent simply could not ask for it.
  * `fallback_used` was in the contract and in no response, so a caller could
    not tell a complete answer from one the filesystem graph carried after the
    CLI dropped out.

WHY A SUBPROCESS AND NOT `create_mcp(...)` IN-PROCESS. The directive is explicit:
judge the Obsidian CLI and the tool surface at the boundary the MCP server
actually runs in, not from the terminal that spawned it. This repository already
had that pattern in `test_vault_retrieval_transports.py`; these cases reuse it
rather than adding a second, weaker way to drive the same tools.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_vault(root: Path) -> None:
    (root / "hub.md").write_text("# Hub\nSee [[target]].\n", encoding="utf-8")
    (root / "second.md").write_text("# Second\n[[target]]\n", encoding="utf-8")
    (root / "target.md").write_text("# Target\nthe answer lives here\n",
                                    encoding="utf-8")
    (root / "orphan.md").write_text("# Orphan\nnothing links here\n",
                                    encoding="utf-8")
    (root / "notes.txt").write_text("not markdown\n", encoding="utf-8")
    (root / "hidden_gold").mkdir(exist_ok=True)
    (root / "hidden_gold" / "gold.md").write_text("# Gold\n", encoding="utf-8")


async def _session(vault: Path, *, obsidian_cli: str | None):
    """Yield an initialised client session against a fresh server process."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env.update({
        "EVIDENCE_VAULT_ROOT": str(vault),
        "PYTHONDONTWRITEBYTECODE": "1",
        # Enabled on purpose: the point of the fallback cases is a server that
        # WANTS the CLI and cannot have it. Disabling Obsidian would test a
        # different thing (a server that never tried).
        "EVIDENCE_OBSIDIAN_ENABLED": "0" if obsidian_cli is None else "1",
    })
    if obsidian_cli is not None:
        env["OBSIDIAN_CLI"] = obsidian_cli
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "evidence_evaluator.retrieval.mcp_server"],
        cwd=str(REPO_ROOT),
        env=env,
    )
    return stdio_client(params), ClientSession


async def _run_contract(vault: Path) -> dict:
    """Every boundary case in one server process, and the findings returned.

    One process for many cases, matching this repository's existing smoke: the
    cases are read-only and independent, and eight process spawns buy nothing.
    """
    pytest.importorskip("mcp")
    client_cm, ClientSession = await _session(vault, obsidian_cli=None)
    found: dict = {}
    async with client_cm as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            found["tools"] = {tool.name for tool in listed.tools}
            found["backlinks_annotations"] = {
                "readOnly": next(t for t in listed.tools
                                 if t.name == "vault_backlinks"
                                 ).annotations.readOnlyHint,
            }

            ok = await session.call_tool("vault_backlinks",
                                         {"path": "target.md", "limit": 10})
            found["ok"] = ok.structuredContent
            found["ok_is_error"] = ok.isError

            bounded = await session.call_tool("vault_backlinks",
                                              {"path": "target.md", "limit": 1})
            found["bounded"] = bounded.structuredContent

            orphan = await session.call_tool("vault_backlinks",
                                             {"path": "orphan.md", "limit": 10})
            found["orphan"] = orphan.structuredContent

            refusals = {}
            for label, path in (("outside", "../escaped.md"),
                                ("private", "hidden_gold/gold.md"),
                                ("non_markdown", "notes.txt"),
                                ("symlink", "escape.md")):
                res = await session.call_tool("vault_backlinks",
                                              {"path": path, "limit": 5})
                refusals[label] = res.isError
            found["refusals"] = refusals

            search = await session.call_tool(
                "vault_search",
                {"query": "answer", "output_k": 4, "candidate_pool_k": 20,
                 "graph_seed_k": 2, "max_turns": 2})
            found["search"] = search.structuredContent
    return found


async def _run_missing_cli(vault: Path) -> dict:
    pytest.importorskip("mcp")
    client_cm, ClientSession = await _session(
        vault, obsidian_cli="/nonexistent/obsidian-v01-test")
    out: dict = {}
    async with client_cm as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            back = await session.call_tool("vault_backlinks",
                                           {"path": "target.md", "limit": 10})
            out["backlinks"] = back.structuredContent
            out["backlinks_is_error"] = back.isError
            search = await session.call_tool(
                "vault_search",
                {"query": "answer", "output_k": 4, "candidate_pool_k": 20,
                 "graph_seed_k": 2, "max_turns": 2})
            out["search"] = search.structuredContent
    return out


@pytest.fixture(scope="module")
def vault(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("v01-vault")
    _build_vault(root)
    outside = root.parent / "escaped_v01.md"
    outside.write_text("# Escaped\n", encoding="utf-8")
    (root / "escape.md").symlink_to(outside)
    return root


@pytest.fixture(scope="module")
def contract(vault: Path) -> dict:
    return asyncio.run(_run_contract(vault))


@pytest.fixture(scope="module")
def missing_cli(vault: Path) -> dict:
    return asyncio.run(_run_missing_cli(vault))


def test_the_server_exposes_the_three_v01_tools(contract):
    assert contract["tools"] == {"vault_search", "vault_read", "vault_backlinks"}


def test_backlinks_is_declared_read_only(contract):
    assert contract["backlinks_annotations"]["readOnly"] is True


def test_backlinks_answers_through_the_tool(contract):
    out = contract["ok"]
    assert contract["ok_is_error"] is False
    assert sorted(out["backlinks"]) == ["hub.md", "second.md"]
    assert out["path"] == "target.md"
    assert "fallback_used" in out


def test_backlinks_is_bounded_at_the_boundary(contract):
    """The same rule as `output_k`. An unbounded list is what the bound exists to
    prevent, and it has to hold at the edge an agent touches."""
    out = contract["bounded"]
    assert len(out["backlinks"]) == 1
    assert out["truncated"] is True
    assert out["discovered_path_count"] == 2


@pytest.mark.parametrize("label", ["outside", "private", "non_markdown", "symlink"])
def test_backlinks_is_fail_closed_on_the_security_boundary(contract, label):
    """These are NOT partial results. Error tolerance covers search providers; it
    does not cover leaving the vault or reading private data."""
    assert contract["refusals"][label] is True, f"{label} was not refused"


def test_zero_backlinks_is_not_reported_as_absence(contract):
    """A document nothing links to must not read as 'checked, none exist'."""
    out = contract["orphan"]
    assert out["backlinks"] == []
    assert out["review_required"] is True


def test_every_search_response_declares_whether_a_fallback_was_used(contract):
    assert "fallback_used" in contract["search"]


def test_a_missing_cli_degrades_the_answer_instead_of_disabling_the_tool(missing_cli):
    """The error-tolerance policy end to end: the CLI the server wanted is gone,
    the call still returns what the filesystem graph knows, and it SAYS which
    source carried it. A degraded run that says nothing is the failure mode."""
    out = missing_cli["backlinks"]
    assert missing_cli["backlinks_is_error"] is False
    assert sorted(out["backlinks"]) == ["hub.md", "second.md"]
    assert out["fallback_used"] == "filesystem"
    assert out["status"] == "partial"
    assert out["review_required"] is True
    assert out["warnings"]


def test_search_names_the_filesystem_fallback_too(missing_cli):
    """`fallback_used` absent means 'none was needed', so it must be non-null
    when one WAS used -- otherwise the field cannot distinguish the two."""
    out = missing_cli["search"]
    assert out["fallback_used"] == "filesystem"
    assert out["review_required"] is True
