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
from evidence_evaluator.retrieval.retriever import RetrievalConfig, RetrievalError
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
