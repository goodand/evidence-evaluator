from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from evidence_evaluator.retrieval.corpus import (
    CanonicalPath,
    CorpusError,
    VaultCorpus,
)
from evidence_evaluator.retrieval.obsidian import (
    ObsidianCliBackend,
    ObsidianGraphResult,
    graph_paths,
    parse_cli_output,
)
from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.retriever import (
    MAX_CANDIDATE_POOL_K,
    MAX_GRAPH_SEED_K,
    MAX_TURNS,
    RetrievalConfig,
    RetrievalError,
)
from evidence_evaluator.retrieval.service import RetrievalService, ServiceError


@pytest.fixture()
def vault_root(tmp_path: Path) -> Path:
    (tmp_path / "deep").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "hidden_gold").mkdir()
    (tmp_path / "private_eval").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "HANDOFF.md").write_text(
        "# Handoff map\n\nfrost resume entry. Continue through [[bridge]].\n",
        encoding="utf-8",
    )
    (tmp_path / "bridge.md").write_text(
        "# Bridge\n\nThe authority is [[deep/authority]].\n",
        encoding="utf-8",
    )
    authority = "# Canonical decision\n\nKeep the worker disabled until review completes.\n"
    (tmp_path / "deep" / "authority.md").write_text(authority, encoding="utf-8")
    (tmp_path / "docs" / "authority-copy.md").write_text(
        authority, encoding="utf-8"
    )
    (tmp_path / "docs" / "authority-alias.md").symlink_to(
        tmp_path / "deep" / "authority.md"
    )
    (tmp_path / "hidden_gold" / "gold.md").write_text(
        "frost resume exact secret answer", encoding="utf-8"
    )
    (tmp_path / "private_eval" / "answer.md").write_text(
        "frost resume private evaluation", encoding="utf-8"
    )
    (tmp_path / ".git" / "secret.md").write_text("frost resume", encoding="utf-8")
    (tmp_path / "UPPER.MD").write_text("# Uppercase\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def profile(vault_root: Path) -> VaultProfile:
    return VaultProfile(
        root=vault_root,
        obsidian_enabled=False,
        authority_prefixes=("deep", "docs"),
        aliases={"frost": ("ice",), "resume": ("handoff",)},
    )


def test_profile_path_policy_is_shared_and_fail_closed(profile: VaultProfile) -> None:
    for path in (
        "hidden_gold/gold.md",
        "private_eval/answer.md",
        ".git/config.md",
        ".venv-rerank/cache.md",
        "../outside.md",
        "/tmp/outside.md",
    ):
        assert profile.is_blocked_path(path), path
    assert not profile.is_blocked_path("docs/ordinary.md")


def test_profile_normalizes_a_string_root(vault_root: Path) -> None:
    assert VaultProfile(root=str(vault_root)).root == vault_root.resolve()


def test_inventory_collapses_replicas_to_configured_authority(
    profile: VaultProfile,
) -> None:
    corpus = VaultCorpus(profile)

    assert "deep/authority.md" in corpus.documents
    assert "docs/authority-copy.md" not in corpus.documents
    document = corpus.documents["deep/authority.md"]
    assert set(document.replica_paths) == {
        "docs/authority-alias.md",
        "docs/authority-copy.md",
    }
    assert corpus.canonicalize("docs/authority-alias.md") == CanonicalPath(
        "deep/authority.md"
    )
    assert all("hidden_gold" not in path for path in corpus.documents)
    assert all("private_eval" not in path for path in corpus.documents)
    assert all(".git" not in path for path in corpus.documents)
    assert "UPPER.MD" in corpus.documents


def test_symlink_and_traversal_reads_are_rejected(profile: VaultProfile) -> None:
    corpus = VaultCorpus(profile)
    with pytest.raises(CorpusError, match="symlink"):
        corpus.read_range("docs/authority-alias.md")
    for path in ("../outside.md", "hidden_gold/gold.md", "note.txt"):
        with pytest.raises(CorpusError):
            corpus.read_range(path)


def test_recall_first_recovers_zero_overlap_authority_by_two_graph_hops(
    profile: VaultProfile,
) -> None:
    service = RetrievalService(profile)
    result = service.search(
        "frost resume",
        output_k=4,
        candidate_pool_k=10,
        graph_seed_k=3,
        max_turns=4,
    )

    assert "deep/authority.md" in result["retrieved_paths"]
    assert any(
        "deep/authority.md" in turn["new_paths"] for turn in result["turns"]
    )
    assert result["turns"][0]["new_paths"] == ["HANDOFF.md"]
    assert any("bridge.md" in turn["new_paths"] for turn in result["turns"])
    assert any(
        "deep/authority.md" in turn["new_paths"] for turn in result["turns"]
    )
    authority = next(
        item for item in result["candidates"] if item["path"] == "deep/authority.md"
    )
    assert "graph" in authority["channel_ranks"]
    # This tiny fixture's graph fully closes within the turn budget --
    # `graph-frontier-exhausted`, not a budget cutoff. See D2
    # (docs/HANDOFF.md): `exhaustive` used to be a hardcoded `False`
    # regardless of `terminal_reason`, which is why this assertion used to
    # read `is False` here too.
    assert result["exhaustive"] is True
    assert result["terminal_reason"] == "graph-frontier-exhausted"


def test_wikilinks_preserve_fully_qualified_paths_with_spaces(tmp_path: Path) -> None:
    target = tmp_path / "Projects" / "Harbor Finch Survey" / "Handoff.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Handoff\n", encoding="utf-8")
    (tmp_path / "Start.md").write_text(
        "[[Projects/Harbor Finch Survey/Handoff|current handoff]]\n",
        encoding="utf-8",
    )

    corpus = VaultCorpus(VaultProfile(root=tmp_path, obsidian_enabled=False))

    assert corpus.links("Start.md") == [
        "Projects/Harbor Finch Survey/Handoff.md"
    ]
    assert corpus.backlinks("Projects/Harbor Finch Survey/Handoff.md") == [
        "Start.md"
    ]


def test_graph_frontier_beats_a_full_lexical_tail(tmp_path: Path) -> None:
    (tmp_path / "deep").mkdir()
    (tmp_path / "HANDOFF.md").write_text(
        "unique entry [[bridge]]", encoding="utf-8"
    )
    (tmp_path / "bridge.md").write_text(
        "neutral [[deep/authority]]", encoding="utf-8"
    )
    (tmp_path / "deep" / "authority.md").write_text(
        "zero lexical overlap", encoding="utf-8"
    )
    for index in range(8):
        (tmp_path / f"lexical-{index}.md").write_text(
            "unique entry noise", encoding="utf-8"
        )
    result = RetrievalService(
        VaultProfile(root=tmp_path, obsidian_enabled=False)
    ).search(
        "unique entry",
        output_k=1,
        candidate_pool_k=2,
        graph_seed_k=1,
        max_turns=4,
    )

    assert any(
        "deep/authority.md" in turn["new_paths"] for turn in result["turns"]
    )
    assert result["discovered_path_count"] >= 3
    assert result["turns"][2]["seed_paths"] == ["bridge.md"]


def test_graph_removal_breaks_the_two_hop_retrieval(profile: VaultProfile) -> None:
    class NoFilesystemGraph(VaultCorpus):
        def links(self, path: str) -> list[str]:
            return []

        def backlinks(self, path: str) -> list[str]:
            return []

    result = RetrievalService(profile, corpus=NoFilesystemGraph(profile)).search(
        "frost resume",
        output_k=4,
        candidate_pool_k=10,
        graph_seed_k=3,
        max_turns=4,
    )
    assert "deep/authority.md" not in result["retrieved_paths"]


class _UnavailableObsidian:
    def neighbors(self, path: CanonicalPath) -> ObsidianGraphResult:
        return ObsidianGraphResult(
            outgoing=("hidden_gold/gold.md",),
            backlinks=("../outside.md",),
            warnings=(f"simulated CLI failure for {path}",),
            available=False,
        )


def test_filesystem_graph_survives_obsidian_failure_and_filters_live_edges(
    profile: VaultProfile,
) -> None:
    corpus = VaultCorpus(profile)
    service = RetrievalService(profile, corpus=corpus, obsidian=_UnavailableObsidian())
    result = service.search(
        "frost resume",
        output_k=4,
        candidate_pool_k=10,
        graph_seed_k=3,
        max_turns=4,
    )

    assert "deep/authority.md" in result["retrieved_paths"]
    assert all("hidden_gold" not in path for path in result["retrieved_paths"])
    assert all("outside" not in path for path in result["retrieved_paths"])
    assert any("simulated CLI failure" in item for item in result["warnings"])


def test_candidate_pool_and_output_are_independent(profile: VaultProfile) -> None:
    service = RetrievalService(profile)
    result = service.search(
        "frost resume",
        output_k=1,
        candidate_pool_k=10,
        graph_seed_k=3,
        max_turns=4,
    )
    assert len(result["candidates"]) == 1
    assert len(result["retrieved_paths"]) == 1
    assert len(result["candidate_pool"]) >= 3
    with pytest.raises(RetrievalError):
        RetrievalConfig(output_k=9, candidate_pool_k=8)


# --- RetrievalConfig validation: one witness per branch --------------------
#
# WHY THIS EXISTS. Mutation analysis (2026-08-17) found the `graph_seed_k`
# branch of `RetrievalConfig.__post_init__` surviving every test, and a poison
# test confirmed it: replacing that branch with `if False:` left the whole
# suite at 131 passed. The only `pytest.raises(RetrievalError)` in this file
# was `RetrievalConfig(output_k=9, candidate_pool_k=8)`, which trips the FIRST
# branch and never reaches the second.
#
# That case also shows why one assertion per branch is not enough. Its default
# `graph_seed_k=12` exceeds `candidate_pool_k=8`, so it violates the second
# branch too -- the first one just raises first. A test that only checks "some
# RetrievalError was raised" cannot tell which branch spoke, so a dead branch
# hides behind a live one. Each case below violates EXACTLY ONE branch, and
# asserts on the message, so the witness names the branch it proves.
#
# The hiding turned out to run BOTH ways. Poison-testing each branch in turn
# (2026-08-17) showed that killing the FIRST branch also leaves
# `test_candidate_pool_and_output_are_independent` passing -- its default
# `graph_seed_k=12` breaks the second bound, so the second branch raises the
# RetrievalError the assertion was waiting for. That test witnesses "some
# bound rejected this config", which neither branch needs to be alive for.
#
# Poison results, whole suite, one branch disabled at a time:
#   output_k branch     -> 3 failed (kwargs0-2), old test still passed
#   graph_seed_k branch -> 3 failed (kwargs3-5)
#   max_turns branch    -> 2 failed (kwargs6-7)
# Each branch is witnessed by exactly its own cases and nothing else.
#
# The guard was never unreachable -- it fired on a real call during this
# session's own work. It was reachable and unwitnessed, which is the harder
# case to notice.

_ONE_BRANCH_EACH = [
    # (kwargs, fragment of the message that branch alone produces)
    ({"output_k": 0}, "output_k"),
    ({"output_k": 9, "candidate_pool_k": 8, "graph_seed_k": 1}, "output_k"),
    ({"candidate_pool_k": MAX_CANDIDATE_POOL_K + 1}, "output_k"),
    ({"graph_seed_k": 0}, "graph_seed_k"),
    ({"graph_seed_k": 51, "candidate_pool_k": 50}, "graph_seed_k"),
    ({"graph_seed_k": MAX_GRAPH_SEED_K + 1,
      "candidate_pool_k": MAX_CANDIDATE_POOL_K}, "graph_seed_k"),
    ({"max_turns": 0}, "max_turns"),
    ({"max_turns": MAX_TURNS + 1}, "max_turns"),
]


@pytest.mark.parametrize("kwargs,expected_fragment", _ONE_BRANCH_EACH)
def test_each_config_bound_rejects_and_says_which_bound(kwargs, expected_fragment):
    with pytest.raises(RetrievalError) as excinfo:
        RetrievalConfig(**kwargs)
    assert expected_fragment in str(excinfo.value), (
        f"{kwargs} raised, but the message did not mention {expected_fragment!r} "
        f"-- it said {str(excinfo.value)!r}. A different branch spoke, so this "
        f"case is not a witness for the branch it was written for."
    )


def test_a_config_inside_every_bound_is_accepted():
    """The negative witness. Without it, validation that rejects EVERYTHING
    would satisfy all eight cases above."""
    config = RetrievalConfig(
        output_k=8,
        candidate_pool_k=MAX_CANDIDATE_POOL_K,
        graph_seed_k=MAX_GRAPH_SEED_K,
        max_turns=MAX_TURNS,
    )
    assert config.graph_seed_k == MAX_GRAPH_SEED_K


def test_transport_paths_are_bounded_even_when_graph_discovers_more(
    profile: VaultProfile,
) -> None:
    result = RetrievalService(profile).search(
        "frost resume",
        output_k=1,
        candidate_pool_k=10,
        graph_seed_k=3,
        max_turns=4,
    )
    assert len(result["retrieved_paths"]) == 1
    assert len(result["candidate_pool"]) <= 10
    assert result["discovered_path_count"] > len(result["retrieved_paths"])


def test_zero_hit_is_structurally_inconclusive(profile: VaultProfile) -> None:
    result = RetrievalService(profile).search(
        "zzzz-no-such-surface",
        output_k=2,
        candidate_pool_k=4,
        graph_seed_k=2,
        max_turns=2,
    )
    assert result["candidates"] == []
    assert result["review_required"] is True
    assert result["exhaustive"] is False
    assert result["terminal_reason"] == "no-lexical-entry"
    assert "inconclusive" in result["next_action"]


def test_non_exhaustive_hit_requires_evidence_review(tmp_path: Path) -> None:
    """A budget cutoff before the graph frontier closes must stay flagged.

    D2 (docs/HANDOFF.md, docs/AUDIT_CLAUDE_MD_VACUOUS_PATTERNS.md): the field
    used to be a hardcoded constant, so it fired the same way regardless of
    what actually happened. This fixture is built so `graph_seed_k=1,
    max_turns=2` cannot reach the end of a 3-hop chain -- the loop exhausts
    its TURN budget, not the graph -- so `terminal_reason` must read
    `turn-budget-exhausted`, not the frontier-closed value.
    """
    (tmp_path / "HANDOFF.md").write_text("needle state [[a1]]", encoding="utf-8")
    (tmp_path / "a1.md").write_text("hop one [[a2]]", encoding="utf-8")
    (tmp_path / "a2.md").write_text("hop two [[a3]]", encoding="utf-8")
    (tmp_path / "a3.md").write_text(
        "hop three, no further needle overlap here", encoding="utf-8"
    )
    result = RetrievalService(
        VaultProfile(root=tmp_path, obsidian_enabled=False)
    ).search(
        "needle",
        output_k=4,
        candidate_pool_k=4,
        graph_seed_k=1,
        max_turns=2,
    )
    assert result["terminal_reason"] == "turn-budget-exhausted"
    assert result["exhaustive"] is False
    assert result["review_required"] is True
    assert result["status"] == "review_required"


def test_a_fully_closed_search_can_report_review_required_false(
    profile: VaultProfile,
) -> None:
    """The other half of the D2 poison test.

    A field that is always true carries the same zero information as one that
    is always false (docs/AUDIT_CLAUDE_MD_VACUOUS_PATTERNS.md). This is the
    direction the earlier hardcoded constant could never produce: a search
    whose graph frontier genuinely closes, with no provider fallback, must be
    able to say so.
    """
    result = RetrievalService(profile).search(
        "frost resume",
        output_k=4,
        candidate_pool_k=10,
        graph_seed_k=3,
        max_turns=4,
    )
    assert result["terminal_reason"] == "graph-frontier-exhausted"
    assert result["warnings"] == []
    assert result["exhaustive"] is True
    assert result["review_required"] is False
    assert result["status"] == "complete"


def test_obsidian_adapter_scopes_every_call_with_cwd_and_canonical_path(
    profile: VaultProfile,
) -> None:
    calls: list[tuple[list[str], object, int]] = []

    def fake_run(command: list[str], cwd: object, timeout: int):
        calls.append((command, cwd, timeout))
        if "backlinks" in command:
            output = json.dumps([{"file": "HANDOFF.md"}])
        else:
            output = "bridge.md\n"
        return subprocess.CompletedProcess(command, 0, output, "")

    backend = ObsidianCliBackend(profile, runner=fake_run)
    result = backend.neighbors(CanonicalPath("deep/authority.md"))

    assert result.backlinks == ("HANDOFF.md",)
    assert result.outgoing == ("bridge.md",)
    assert len(calls) == 2
    assert all(cwd == profile.root for _, cwd, _ in calls)
    assert all("path=deep/authority.md" in command for command, _, _ in calls)
    assert all("authority-alias" not in " ".join(command) for command, _, _ in calls)


def test_obsidian_output_parsing_rejects_non_path_noise() -> None:
    assert parse_cli_output("No backlinks found") == []
    assert graph_paths({"docs/a.md": 2, "tag": "#status/active"}) == [
        "docs/a.md"
    ]
    assert graph_paths([{"path": "[[docs/b.md|B]]"}, "docs/c.md\t3"]) == [
        "docs/b.md",
        "docs/c.md",
    ]
    assert graph_paths({"message": "bad", "line": "target.md:12"}) == []
    assert graph_paths("Failed to connect\nhttps://example.test/x.md") == []


def test_markdown_link_title_resolves_to_its_destination(tmp_path: Path) -> None:
    (tmp_path / "source.md").write_text(
        "[authority](target.md \"Tooltip\") [again](target.md (Tooltip))",
        encoding="utf-8",
    )
    (tmp_path / "target.md").write_text("# Target\n", encoding="utf-8")
    corpus = VaultCorpus(VaultProfile(root=tmp_path, obsidian_enabled=False))
    assert corpus.links("source.md") == ["target.md"]


def test_rc_zero_connection_error_is_not_a_live_graph_success(
    profile: VaultProfile,
) -> None:
    def fake_run(command: list[str], cwd: object, timeout: int):
        return subprocess.CompletedProcess(command, 0, "Failed to connect", "")

    result = ObsidianCliBackend(profile, runner=fake_run).neighbors(
        CanonicalPath("HANDOFF.md")
    )
    assert result.available is False
    assert len(result.warnings) == 2


def test_unavailable_path_is_retried_without_disabling_other_paths(
    profile: VaultProfile,
) -> None:
    calls: list[list[str]] = []

    def fake_run(command: list[str], cwd: object, timeout: int):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            1,
            "The CLI is unable to find Obsidian.",
            "",
        )

    backend = ObsidianCliBackend(profile, runner=fake_run)
    first = backend.neighbors(CanonicalPath("HANDOFF.md"))
    second = backend.neighbors(CanonicalPath("bridge.md"))
    assert len(calls) == 8  # Two commands and one retry for each path.
    assert first.available is False
    assert len(first.warnings) == 2
    assert second.available is False
    assert len(second.warnings) == 2


def test_service_read_is_bounded_and_hashed(profile: VaultProfile) -> None:
    result = RetrievalService(profile).read(
        "deep/authority.md", line_start=2, line_count=1
    )
    assert result["canonical_path"] == "deep/authority.md"
    assert result["line_start"] == 2
    assert len(result["document_sha256"]) == 64
    assert len(result["content_sha256"]) == 64
    with pytest.raises(ServiceError):
        RetrievalService(profile).read("deep/authority.md", line_count=401)


def test_vault_corpus_matches_runner_subagent_interface(profile: VaultProfile) -> None:
    package_dir = Path(__file__).resolve().parents[1] / "evidence_evaluator"
    sys.path.insert(0, str(package_dir))
    try:
        from runner import retrieval_subagent

        result = retrieval_subagent(
            VaultCorpus(profile),
            {"query": "frost resume"},
        )
    finally:
        sys.path.remove(str(package_dir))

    assert result["candidate_paths"][0] == "HANDOFF.md"
    assert "bridge.md" in result["candidate_paths"]
    assert result["uncertainty"].startswith("candidates only")


# ------------------------------------------------------------- v0.1 gaps ----
# Audited 2026-08-12 against the v0.1 tool contract (docs/PLAN_V01_AUDIT_AND_GAPS.md).
# Two things blocked v0.1: `vault_backlinks` was not exposed (the CAPABILITY was
# already there, used inside the graph walk), and `fallback_used` was absent from
# every response even though the error-tolerance contract requires it.

def _svc(tmp_path, **profile_kw):
    from evidence_evaluator.retrieval.profile import VaultProfile
    from evidence_evaluator.retrieval.service import RetrievalService
    return RetrievalService.from_profile(
        VaultProfile(root=str(tmp_path), vault_name="t", **profile_kw))


def _vault(tmp_path):
    (tmp_path / "hub.md").write_text(
        "# Hub\nSee [[target]] and [[other]].\n", encoding="utf-8")
    (tmp_path / "second.md").write_text("# Second\n[[target]]\n", encoding="utf-8")
    (tmp_path / "target.md").write_text("# Target\nthe answer\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("# Other\n", encoding="utf-8")
    return tmp_path


def test_backlinks_returns_the_documents_that_link_here(tmp_path):
    """B1. The graph walk already computed backlinks internally; an agent could
    not ASK for them. This is the third v0.1 tool."""
    svc = _svc(_vault(tmp_path))
    out = svc.backlinks("target.md", limit=10)
    assert out["status"] in ("ok", "partial")
    assert sorted(out["backlinks"]) == ["hub.md", "second.md"]
    assert out["path"] == "target.md"
    assert "fallback_used" in out


@pytest.mark.parametrize("bad,why", [
    ("../outside.md", "vault 밖"),
    ("hidden_gold/gold.json", "private"),
    ("notes.txt", "non-Markdown"),
])
def test_backlinks_refuses_what_read_refuses(tmp_path, bad, why):
    """B2/B3/B5. The same boundary as `read`, not a second one -- a second copy
    of a security check is a copy that can drift."""
    svc = _svc(_vault(tmp_path))
    with pytest.raises(Exception) as exc:
        svc.backlinks(bad, limit=5)
    assert exc.type.__name__ in ("ServiceError", "ProfileError", "ValueError"), why


def test_backlinks_refuses_a_symlink_escape(tmp_path):
    """B4. A link pointing outside must not become a readable path."""
    outside = tmp_path.parent / "escape_target.md"
    outside.write_text("# Escaped\n", encoding="utf-8")
    vault = _vault(tmp_path)
    (vault / "escape.md").symlink_to(outside)
    svc = _svc(vault)
    with pytest.raises(Exception):
        svc.backlinks("escape.md", limit=5)


def test_backlinks_respects_limit(tmp_path):
    """B6. An unbounded list is what the output_k invariant exists to prevent;
    the same rule has to hold on this tool."""
    svc = _svc(_vault(tmp_path))
    out = svc.backlinks("target.md", limit=1)
    assert len(out["backlinks"]) == 1
    assert out["truncated"] is True


def test_backlinks_falls_back_to_the_filesystem_when_the_cli_is_gone(tmp_path):
    """B7. The whole error-tolerance policy in one test: the CLI is absent, the
    call still returns evidence, and it SAYS the fallback was used."""
    svc = _svc(_vault(tmp_path), obsidian_binary="/nonexistent/obsidian")
    out = svc.backlinks("target.md", limit=10)
    assert sorted(out["backlinks"]) == ["hub.md", "second.md"]
    assert out["fallback_used"] == "filesystem"
    assert out["status"] == "partial"
    assert out["warnings"], "a degraded run must say so"


def test_every_search_response_declares_whether_a_fallback_was_used(tmp_path):
    """F1. The contract lists `fallback_used`; it was in no response."""
    out = _svc(_vault(tmp_path)).search("answer", output_k=4, candidate_pool_k=20)
    assert "fallback_used" in out


def test_search_names_the_filesystem_fallback_when_the_cli_is_gone(tmp_path):
    """F2. Absent means "no fallback was needed", so it must not be absent when
    one WAS used -- otherwise the field cannot distinguish the two."""
    svc = _svc(_vault(tmp_path), obsidian_binary="/nonexistent/obsidian")
    out = svc.search("answer", output_k=4, candidate_pool_k=20)
    assert out["fallback_used"] == "filesystem"
    assert out["review_required"] is True


def test_querying_a_symlink_path_signals_that_it_was_resolved(tmp_path):
    """Symlink-alias signal for vault-backlinks-mcp adapter parity.

    A symlink is never content authority (symlink-vs-moc-2026-07-30, adopted
    hybrid #6) -- `canonicalize()` already resolves it silently. This proves
    the caller can ALSO learn that resolution happened, without the answer
    itself changing: same backlinks, same path, one extra warning.
    """
    vault = _vault(tmp_path)
    (vault / "target-alias.md").symlink_to(vault / "target.md")
    svc = _svc(vault)

    direct = svc.backlinks("target.md", limit=10)
    via_symlink = svc.backlinks("target-alias.md", limit=10)

    assert via_symlink["path"] == direct["path"] == "target.md"
    assert sorted(via_symlink["backlinks"]) == sorted(direct["backlinks"])
    assert any("symlink" in w.casefold() for w in via_symlink["warnings"])
    assert not any("symlink" in w.casefold() for w in direct["warnings"]), (
        "poison test: the signal must NOT fire for a non-symlink query"
    )
    assert via_symlink["review_required"] is True


def test_backlinks_only_issues_a_single_cli_call(tmp_path):
    """`backlinks_only()` exists so a caller that never reads `links` doesn't
    pay for the extra CLI round trip `neighbors()` always makes (one more
    chance of a transient IPC failure for data that call site discards)."""
    from evidence_evaluator.retrieval.corpus import CanonicalPath
    from evidence_evaluator.retrieval.obsidian import ObsidianCliBackend
    from evidence_evaluator.retrieval.profile import VaultProfile
    import subprocess

    calls = []

    def fake_run(command, cwd, timeout):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '[{"file": "hub.md"}]', "")

    profile = VaultProfile(root=str(_vault(tmp_path)), vault_name="t")
    backend = ObsidianCliBackend(profile, runner=fake_run)
    result = backend.backlinks_only(CanonicalPath("target.md"))

    assert result.backlinks == ("hub.md",)
    assert result.available is True
    assert len(calls) == 1, f"expected exactly one CLI call, got {len(calls)}"
    assert calls[0][1] == "backlinks" and "links" not in calls[0][1:]


def test_backlinks_only_reports_unavailable_on_cli_failure(tmp_path):
    """Adversarial review 2026-08-15: asserting only `available is False` +
    empty backlinks + truthy warnings let a hardcoded
    `ObsidianBacklinksResult(available=False, warnings=("anything",))` that
    never consults the runner pass unchanged. Assert the runner was actually
    invoked and that the warning names the real failure, so the result has
    to be derived from the CLI call rather than assumed."""
    from evidence_evaluator.retrieval.corpus import CanonicalPath
    from evidence_evaluator.retrieval.obsidian import ObsidianCliBackend
    from evidence_evaluator.retrieval.profile import VaultProfile
    import subprocess

    calls = []

    def failing_run(command, cwd, timeout):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "unable to find Obsidian")

    profile = VaultProfile(root=str(_vault(tmp_path)), vault_name="t")
    backend = ObsidianCliBackend(profile, runner=failing_run)
    result = backend.backlinks_only(CanonicalPath("target.md"))

    assert calls, "the CLI runner was never invoked"
    assert calls[0][1] == "backlinks"
    assert result.available is False
    assert result.backlinks == ()
    assert result.warnings
    # The warning must carry the actual failure detail, not a generic string.
    assert "target.md" in result.warnings[0]
    assert "unable to find Obsidian" in result.warnings[0]


# --- D1b/D3: ranking demotion (2026-08-16) -------------------------------
# Measured on the real vault before this existed: a direct-keyword query
# returned four superseded `archive/` copies in its top four while the current
# document sat outside the output window, and a known-answer query returned
# three generated MOC indexes ahead of the decision document they index.
# Recall over the 5-question set went 3/5 -> 4/5 with demotion configured.

def _tiered_vault(tmp_path):
    """Two documents that both answer the query. The archived one is shorter,
    so BM25 length normalization ranks it FIRST without demotion -- that is
    the defect this reproduces, not a contrived tie."""
    (tmp_path / "archive").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "archive" / "old.md").write_text(
        "widget calibration procedure\n", encoding="utf-8")
    (tmp_path / "docs" / "current.md").write_text(
        "widget calibration procedure, with the additional detail that makes "
        "this the longer and therefore BM25-disfavoured document\n",
        encoding="utf-8")
    return tmp_path


def test_without_demotion_the_archived_copy_wins(tmp_path):
    """The baseline the fix has to beat. If this ever stops holding, the
    demotion test below stops proving anything and both need rewriting."""
    out = _svc(_tiered_vault(tmp_path)).search(
        "widget calibration procedure", output_k=2, candidate_pool_k=10, graph_seed_k=4)
    assert out["retrieved_paths"][0] == "archive/old.md"


def test_demoted_paths_rank_below_equally_relevant_current_ones(tmp_path):
    out = _svc(_tiered_vault(tmp_path), demoted_prefixes=("archive/",)).search(
        "widget calibration procedure", output_k=2, candidate_pool_k=10, graph_seed_k=4)
    assert out["retrieved_paths"][0] == "docs/current.md"
    # Demotion reorders; it must not drop the demoted document.
    assert "archive/old.md" in out["retrieved_paths"], (
        "demotion must change ORDER, not membership -- archived material is "
        "still real evidence a caller may need"
    )


def test_demotion_does_not_reorder_within_a_tier(tmp_path):
    """Two demoted documents keep their relative relevance order; demotion is
    a tier boundary, not a re-scoring."""
    vault = _tiered_vault(tmp_path)
    (vault / "archive" / "older.md").write_text(
        "widget calibration procedure detail detail detail detail\n",
        encoding="utf-8")
    plain = _svc(vault).search("widget calibration procedure",
                               output_k=5, candidate_pool_k=10, graph_seed_k=4)["retrieved_paths"]
    demoted = _svc(vault, demoted_prefixes=("archive/",)).search(
        "widget calibration procedure", output_k=5,
        candidate_pool_k=10, graph_seed_k=4)["retrieved_paths"]
    within = lambda paths: [p for p in paths if p.startswith("archive/")]
    assert within(plain) == within(demoted)


def test_env_carries_ranking_policy_into_the_profile(tmp_path, monkeypatch):
    """D1a's root cause: `from_env()` accepted only root/vault-name/CLI flags,
    so an MCP server started with EVIDENCE_VAULT_ROOT -- the normal way it is
    launched -- silently ran with NO authority order and NO demotion. The
    policy existed and was unreachable."""
    monkeypatch.setenv("EVIDENCE_VAULT_ROOT", str(tmp_path))
    monkeypatch.setenv("EVIDENCE_VAULT_AUTHORITY_PREFIXES", "docs/, notes/audits/")
    monkeypatch.setenv("EVIDENCE_VAULT_DEMOTED_PREFIXES", "archive/")
    monkeypatch.setenv("EVIDENCE_VAULT_EXCLUDED_GLOBS", "*.tmp.md")
    monkeypatch.delenv("EVIDENCE_VAULT_PROFILE", raising=False)

    profile = VaultProfile.from_env()
    assert profile.authority_prefixes == ("docs/", "notes/audits/")
    assert profile.demoted_prefixes == ("archive/",)
    assert profile.excluded_globs == ("*.tmp.md",)
    assert profile.is_demoted("archive/anything.md") is True
    assert profile.is_demoted("docs/anything.md") is False


def test_a_coarse_authority_prefix_also_matches_nested_worktrees(tmp_path):
    """Recorded because it cost a wrong conclusion once (2026-08-16): prefixes
    match by string, so `concept-gate-taxonomy/` also matches
    `concept-gate-taxonomy/.claude/worktrees/.../docs/`, and the nested copy
    can win the canonical slot. Precision is the caller's job; this test
    exists so the behavior is stated rather than discovered again."""
    profile = VaultProfile(root=tmp_path, authority_prefixes=("proj/",))
    coarse_tier, _ = profile.authority_rank("proj/.worktrees/x/docs/a.md")
    true_tier, _ = profile.authority_rank("proj/docs/a.md")
    assert coarse_tier == true_tier, "a coarse prefix cannot separate these"

    precise = VaultProfile(root=tmp_path, authority_prefixes=("proj/docs/",))
    assert precise.authority_rank("proj/docs/a.md")[0] < \
        precise.authority_rank("proj/.worktrees/x/docs/a.md")[0]


# --- D3: graph channel ranked by connection evidence (2026-08-16) ---------
# Design ruling: docs/DESIGN_DECISION_D3_GRAPH_RANK_20260816.md

def test_graph_channel_ranks_by_parent_count_not_discovery_order():
    """The unit the whole fix turns on. `graph_channel_order` is handed a
    discovery-ordered list and must NOT preserve that order when connection
    evidence disagrees."""
    from evidence_evaluator.retrieval.retriever import graph_channel_order
    discovered = ["found-first.md", "found-later.md"]
    evidence = {
        "found-first.md": [{"seed": "a.md", "relation": "outgoing"}],
        "found-later.md": [{"seed": "a.md", "relation": "outgoing"},
                           {"seed": "b.md", "relation": "backlink"},
                           {"seed": "c.md", "relation": "backlink"}],
    }
    depth = {"found-first.md": 2, "found-later.md": 2}
    order = graph_channel_order(discovered, evidence, depth, {})
    assert order[0] == "found-later.md", (
        "three distinct parents must outrank one, regardless of which was "
        "seen first"
    )


def test_graph_channel_prefers_shallower_when_parent_counts_tie():
    from evidence_evaluator.retrieval.retriever import graph_channel_order
    ev = {p: [{"seed": "a.md", "relation": "outgoing"}]
          for p in ("far.md", "near.md")}
    order = graph_channel_order(["far.md", "near.md"], ev,
                                {"far.md": 5, "near.md": 2}, {})
    assert order[0] == "near.md"


def test_graph_channel_prefers_a_lexically_stronger_parent_on_a_tie():
    """A link from a document the query actually matched is better evidence
    than a link from an unrelated one."""
    from evidence_evaluator.retrieval.retriever import graph_channel_order
    ev = {"via-weak.md": [{"seed": "weak.md", "relation": "outgoing"}],
          "via-strong.md": [{"seed": "strong.md", "relation": "outgoing"}]}
    depth = {"via-weak.md": 2, "via-strong.md": 2}
    order = graph_channel_order(["via-weak.md", "via-strong.md"], ev, depth,
                                {"strong.md": 1, "weak.md": 40})
    assert order[0] == "via-strong.md"


def test_the_zero_overlap_answer_survives_in_the_output_not_just_discovery(tmp_path):
    """Asserts the OUTPUT, which the neighbouring
    `test_graph_frontier_beats_a_full_lexical_tail` does not: that one checks
    only discovery (`turn["new_paths"]`) and never inspects
    `retrieved_paths`, so it passes even when the answer is pushed out of the
    output window entirely.

    SCOPE, measured rather than assumed: this catches a LEXICAL-FIRST
    ordering (staged ranking buries the answer at position
    lexical_matches + 2, so it leaves the window here). It does NOT catch the
    discovery-order graph channel that D3 fixed -- reverting that change
    leaves this test green. Four synthetic fixtures were tried; none
    reproduced the real vault's in/out flip, which needs that corpus's scale
    and link topology. The regression guard for D3 is
    `scripts/d3_ranking_gates.py` against the real vault. See
    docs/DESIGN_DECISION_D3_GRAPH_RANK_20260816.md section 4.
    """
    (tmp_path / "deep").mkdir()
    (tmp_path / "HANDOFF.md").write_text("unique entry [[bridge]]", encoding="utf-8")
    (tmp_path / "bridge.md").write_text("neutral [[deep/authority]]",
                                        encoding="utf-8")
    (tmp_path / "deep" / "authority.md").write_text("zero lexical overlap",
                                                    encoding="utf-8")
    for i in range(30):
        # Distinct bodies: byte-identical files collapse into one document via
        # replica dedup, which silently defeated an earlier version of this.
        (tmp_path / f"lexical-{i:03d}.md").write_text(
            f"unique entry noise variant {i} filler-{i}", encoding="utf-8")

    out = RetrievalService(
        VaultProfile(root=tmp_path, obsidian_enabled=False)
    ).search("unique entry", output_k=8, candidate_pool_k=50,
             graph_seed_k=4, max_turns=4)
    assert "deep/authority.md" in out["retrieved_paths"], (
        "the answer shares no vocabulary with the query and is only reachable "
        "through the graph -- if it leaves the output, this package has lost "
        "the capability it exists for"
    )


def test_graph_rank_is_stable_as_seed_count_grows(tmp_path):
    """Raising graph_seed_k must not knock the answer out of the output.

    SCOPE, same caveat as the test above: on the real vault the old
    discovery-order channel degraded monotonically here (rank 4 -> 6 -> gone
    at seed 4/8/12), but this synthetic corpus is too small to reproduce
    that -- the test stays green with the fix reverted. Kept as a smoke check
    that seed count does not destabilise output at all; the real guard is
    `scripts/d3_ranking_gates.py` gate 4."""
    (tmp_path / "deep").mkdir()
    (tmp_path / "HANDOFF.md").write_text("unique entry [[bridge]]", encoding="utf-8")
    (tmp_path / "bridge.md").write_text("neutral [[deep/authority]]",
                                        encoding="utf-8")
    (tmp_path / "deep" / "authority.md").write_text("zero lexical overlap",
                                                    encoding="utf-8")
    for i in range(20):
        (tmp_path / f"noise-{i:03d}.md").write_text(
            f"unique entry noise variant {i} filler-{i}", encoding="utf-8")
    svc = RetrievalService(VaultProfile(root=tmp_path, obsidian_enabled=False))

    ranks = []
    for seed_k in (2, 4, 8, 16):
        out = svc.search("unique entry", output_k=8, candidate_pool_k=50,
                         graph_seed_k=seed_k, max_turns=4)
        r = next((i + 1 for i, p in enumerate(out["retrieved_paths"])
                  if p == "deep/authority.md"), None)
        ranks.append(r)
    assert all(r is not None for r in ranks), (
        f"answer dropped out of the output at some seed count: {ranks}")
    assert max(ranks) - min(ranks) <= 4, f"rank swings with seed count: {ranks}"
