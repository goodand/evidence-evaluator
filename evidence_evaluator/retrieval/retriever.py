"""Deterministic recall-first retrieval over lexical and graph channels."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

from .corpus import CanonicalPath, VaultCorpus
from .obsidian import ObsidianCliBackend


RRF_CONSTANT = 60
MAX_OUTPUT_K = 500
MAX_CANDIDATE_POOL_K = 500
MAX_GRAPH_SEED_K = 500
MAX_TURNS = 20


class RetrievalError(ValueError):
    """Raised when a retrieval request cannot be executed safely."""


@dataclass(frozen=True)
class RetrievalConfig:
    output_k: int = 8
    candidate_pool_k: int = 50
    graph_seed_k: int = 12
    max_turns: int = 6

    def __post_init__(self) -> None:
        if not 1 <= self.output_k <= self.candidate_pool_k <= MAX_CANDIDATE_POOL_K:
            raise RetrievalError(
                "Require 1 <= output_k <= candidate_pool_k <= "
                f"{MAX_CANDIDATE_POOL_K}"
            )
        if not 1 <= self.graph_seed_k <= min(
            self.candidate_pool_k, MAX_GRAPH_SEED_K
        ):
            raise RetrievalError(
                "Require 1 <= graph_seed_k <= candidate_pool_k"
            )
        if not 1 <= self.max_turns <= MAX_TURNS:
            raise RetrievalError(f"Require 1 <= max_turns <= {MAX_TURNS}")


def reciprocal_rank_fusion(
    channels: dict[str, Iterable[str]],
    *,
    weights: dict[str, float] | None = None,
) -> tuple[list[tuple[str, float]], dict[str, dict[str, int]]]:
    weights = weights or {}
    scores: dict[str, float] = defaultdict(float)
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for channel, values in channels.items():
        for rank, path in enumerate(dict.fromkeys(values), start=1):
            scores[path] += weights.get(channel, 1.0) / (RRF_CONSTANT + rank)
            ranks[path][channel] = rank
    ordered = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    return ordered, dict(ranks)


def graph_channel_order(
    discovered_paths: list[str],
    evidence: dict[str, list[dict[str, str]]],
    depth: dict[str, int],
    lexical_rank: dict[str, int],
) -> list[str]:
    """Order the graph channel by connection evidence, not discovery order.

    WHY THIS EXISTS. `reciprocal_rank_fusion` scores a channel by POSITION in
    the list it is handed. The graph channel used to be handed
    `graph_order` -- append-on-first-sighting -- so a document's graph score
    was decided by which seed happened to expand first, and nothing else.
    Measured on a real 1,766-document vault: a document ranked bm25 #1 and
    exact #2 (the best lexical match in the corpus) landed at graph position
    183 and fell out of the top 8, beaten by a document with NO lexical match
    at all sitting at graph position 35. Raising `graph_seed_k` made it
    strictly worse (rank 4 -> 6 -> gone), because more seeds append more
    neighbours ahead of it.

    Ranked instead by, in order:

    1. how many DISTINCT parents in this query's own walk link to it --
       query-local, not the vault's global backlink count. A globally
       popular page should not outrank a page this query's neighbourhood
       actually converges on (Topic-Sensitive PageRank's argument).
    2. shallower first -- a document two hops from a lexical seed is closer
       evidence than one five hops out.
    3. the best lexical standing among its parents -- a link from a strong
       match is better evidence than a link from an unrelated document.
    4. path, so the result is deterministic.

    The multiplicity input was already being collected: `graph_evidence` is
    appended OUTSIDE the `if neighbor not in graph_order` guard, so it holds
    every distinct (seed, relation) that reached each path. Only the
    discovery-ordered list was ever handed to the fusion step.

    Design ruling and its literature basis (WebQuery's connectivity
    re-ranking, Henzinger's query-dependent indegree, ObjectRank's authority
    flow): docs/DESIGN_DECISION_D3_GRAPH_RANK_20260816.md.
    """
    worst_lexical = len(lexical_rank) + 1

    def key(path: str) -> tuple[int, int, int, str]:
        parents = {item["seed"] for item in evidence.get(path, ())}
        best_parent = min(
            (lexical_rank.get(parent, worst_lexical) for parent in parents),
            default=worst_lexical,
        )
        # `depth[path]`, not `.get(path, 0)`. Mutation analysis (2026-08-17)
        # found the default surviving every test, and instrumenting the real
        # vault confirmed why: `graph_depth.setdefault()` runs for every
        # neighbour the walk touches, so across 50 calls not one path was
        # missing. The default was unreachable -- a defensive-looking branch
        # that no caller could enter and no test could exercise. Indexing
        # directly turns a silently-wrong sort key into a KeyError if that
        # invariant ever breaks.
        return (-len(parents), depth[path], best_parent, path)

    return sorted(discovered_paths, key=key)


class RecallFirstRetriever:
    def __init__(
        self,
        corpus: VaultCorpus,
        obsidian: ObsidianCliBackend | None = None,
    ):
        self.corpus = corpus
        self.obsidian = obsidian

    def retrieve(self, query: str, config: RetrievalConfig) -> dict:
        if not query.strip():
            raise RetrievalError("Query must not be empty")
        expanded_queries = self.corpus.profile.expand_query(query)
        exact = [
            path
            for path, _ in self.corpus.exact_rank(
                expanded_queries, config.candidate_pool_k
            )
        ]
        bm25 = [
            path
            for path, _ in self.corpus.bm25_rank(
                expanded_queries, config.candidate_pool_k
            )
        ]
        channels: dict[str, list[str]] = {"exact": exact, "bm25": bm25}
        ranked, channel_ranks = reciprocal_rank_fusion(channels)
        cumulative = [path for path, _ in ranked[: config.candidate_pool_k]]
        discovered = set(cumulative)
        expanded: set[str] = set()
        graph_order: list[str] = []
        graph_frontier: list[str] = []
        graph_evidence: dict[str, list[dict[str, str]]] = defaultdict(list)
        # Turn at which each path was first reached by the walk. Recoverable
        # from `turns[i]["new_paths"]` after the fact, but the ranking below
        # needs it while the walk is still running.
        graph_depth: dict[str, int] = {}
        # Best lexical standing of any document, used to weigh the PARENTS
        # that link to a candidate: a link from a strong lexical match is
        # better evidence than a link from an unrelated document.
        lexical_rank = {path: index for index, path in enumerate(exact, start=1)}
        for index, path in enumerate(bm25, start=1):
            lexical_rank[path] = min(lexical_rank.get(path, index), index)
        warnings = list(self.corpus.warnings)
        graph_probe_failures: list[tuple[str, str]] = []
        turns = [
            {
                "turn": 1,
                "action": "initial-hybrid",
                "query": query,
                "new_paths": list(cumulative),
                "new_path_count": len(cumulative),
                "seed_paths": [],
            }
        ]

        terminal_reason = "turn-budget-exhausted"
        for turn_number in range(2, config.max_turns + 1):
            ranked, channel_ranks = reciprocal_rank_fusion(
                channels, weights={"graph": 3.0}
            )
            current_pool = [path for path, _ in ranked[: config.candidate_pool_k]]
            # A graph discovery is a retrieval lead, not merely a weak score.
            # Expand it before unrelated lexical tail candidates can starve a
            # multi-hop chain from the fixed-size display pool.
            seeds = list(
                dict.fromkeys(
                    [
                        path
                        for path in graph_frontier
                        if path not in expanded
                    ]
                    + [path for path in current_pool if path not in expanded]
                )
            )[: config.graph_seed_k]
            if not seeds:
                terminal_reason = (
                    "no-lexical-entry" if not cumulative else "graph-frontier-exhausted"
                )
                break

            new_paths: list[str] = []
            for seed_path in seeds:
                expanded.add(seed_path)
                seed = CanonicalPath(seed_path)
                edge_sets: list[tuple[str, list[str]]] = [
                    ("outgoing", self.corpus.links(seed_path)),
                    ("backlink", self.corpus.backlinks(seed_path)),
                ]
                if self.obsidian is not None:
                    live = self.obsidian.neighbors(seed)
                    warnings.extend(live.warnings)
                    graph_probe_failures.extend(live.failures)
                    live_outgoing = self._canonicalize_live(live.outgoing, seed)
                    live_backlinks = self._canonicalize_live(live.backlinks, seed)
                    edge_sets.extend(
                        (("obsidian-outgoing", live_outgoing), ("obsidian-backlink", live_backlinks))
                    )
                for relation, neighbors in edge_sets:
                    for neighbor in neighbors:
                        if neighbor not in graph_order:
                            graph_order.append(neighbor)
                        evidence = {"seed": seed_path, "relation": relation}
                        if evidence not in graph_evidence[neighbor]:
                            graph_evidence[neighbor].append(evidence)
                        if neighbor not in discovered:
                            discovered.add(neighbor)
                            cumulative.append(neighbor)
                            graph_frontier.append(neighbor)
                            new_paths.append(neighbor)
                        graph_depth.setdefault(neighbor, turn_number)

            channels["graph"] = graph_channel_order(
                graph_order, graph_evidence, graph_depth, lexical_rank
            )
            ranked, channel_ranks = reciprocal_rank_fusion(
                channels, weights={"graph": 3.0}
            )
            turns.append(
                {
                    "turn": turn_number,
                    "action": "graph-deepen",
                    "query": query,
                    # The search may discover a high-degree graph node. Keep
                    # trace payloads bounded; the full graph only affects
                    # internal ranking, not the transport's context budget.
                    "new_paths": new_paths[: config.candidate_pool_k],
                    "new_path_count": len(new_paths),
                    "seed_paths": seeds,
                }
            )
            if not new_paths and all(path in expanded for path, _ in ranked):
                terminal_reason = "graph-frontier-exhausted"
                break

        ranked, channel_ranks = reciprocal_rank_fusion(
            channels, weights={"graph": 3.0}
        )
        # Demotion is applied to the ORDER, never to membership: a demoted
        # path that earned its way into the pool stays in the pool, it just
        # sorts after equally-relevant current material. Relevance order
        # within each tier is untouched, so with no `demoted_prefixes`
        # configured this is exactly the previous ranking.
        ranked = sorted(
            ranked,
            key=lambda item: (self.corpus.profile.is_demoted(item[0]), -item[1], item[0]),
        )
        pool_paths = [path for path, _ in ranked[: config.candidate_pool_k]]
        selected_paths = pool_paths[: config.output_k]
        score_by_path = dict(ranked)
        candidates = []
        for rank, path in enumerate(selected_paths, start=1):
            document = self.corpus.documents[path]
            candidates.append(
                {
                    "rank": rank,
                    "path": path,
                    "canonical_path": path,
                    "replica_paths": list(document.replica_paths),
                    "title": document.title,
                    "score": score_by_path[path],
                    "channel_ranks": channel_ranks.get(path, {}),
                    "graph_evidence": graph_evidence.get(path, []),
                }
            )
        return {
            "query": query,
            "expanded_queries": expanded_queries,
            "config": {
                "output_k": config.output_k,
                "candidate_pool_k": config.candidate_pool_k,
                "graph_seed_k": config.graph_seed_k,
                "max_turns": config.max_turns,
            },
            "candidate_pool": pool_paths,
            # `retrieved_paths` is the caller-visible output set, not every
            # internal graph discovery. `candidate_pool` remains available
            # for a controller that deliberately wants to inspect more leads.
            "retrieved_paths": selected_paths,
            "discovered_path_count": len(discovered),
            "candidates": candidates,
            "turns": turns,
            "warnings": list(dict.fromkeys(warnings)),
            # Typed (code, path) per failed CLI probe, from the obsidian
            # layer's classification. Carried as data so the service can emit
            # coded review_checks instead of re-deriving the reason from the
            # warning text -- which is how "these paths are not indexed" got
            # aggregated into a message reading "the CLI is down"
            # (docs/INDEPENDENT_TEST_HAIKU_MCP_20260822.md).
            "graph_probe_failures": [
                {"code": code, "path": path}
                for code, path in dict.fromkeys(graph_probe_failures)
            ],
            "terminal_reason": terminal_reason,
            # Exhaustive means the search ran out of graph to explore, not
            # merely out of turns. A budget cutoff or an empty lexical seed is
            # genuinely inconclusive; the search space closing on its own is
            # not. `turn-budget-exhausted` was also the loop's own default
            # value regardless of outcome, which is why this used to be a
            # hardcoded `False` -- see docs/HANDOFF.md D2.
            "exhaustive": terminal_reason == "graph-frontier-exhausted",
        }

    def _canonicalize_live(
        self,
        values: Iterable[str],
        seed: CanonicalPath,
    ) -> list[str]:
        paths: list[str] = []
        for value in values:
            target = self.corpus.resolve_graph_target(value, source=seed)
            if target is not None and target.relative not in paths:
                paths.append(target.relative)
        return paths
