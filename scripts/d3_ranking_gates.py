"""The four gates the design ruling requires, runnable BEFORE and AFTER a
change so "it passed" is a comparison rather than an assertion.

Gate 3 is written here rather than delegated to
`test_graph_frontier_beats_a_full_lexical_tail`: that test asserts only
discovery (`turn["new_paths"]`) and never inspects `retrieved_paths`, so it
passes even when the answer vanishes from the output. See
docs/DESIGN_DECISION_D3_GRAPH_RANK_20260816.md section 3e.

Usage: python3 d3_gates.py [label]
"""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator/"
                   ".claude/worktrees/mcp-v01-backlinks")

from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.service import RetrievalService
from evidence_evaluator.retrieval.corpus import VaultCorpus
from evidence_evaluator.retrieval.retriever import RecallFirstRetriever, RetrievalConfig

VAULT = "/Users/jaehyuntak/Desktop/Project_in_progress"
DEMOTED = ("archive/", "notes/00-moc/")
LABEL = sys.argv[1] if len(sys.argv) > 1 else "current"

CASES = [
    ("C1", "concept gate obligation layer roadmap", "obligation_layer_roadmap"),
    ("C2", "handoff reuse validation standard for zero-context agents",
     "HANDOFF_REUSE_VALIDATION"),
    ("C3", "symlink versus MOC decision for canonical directory layout",
     "symlink-vs-moc"),
    ("C4", "HANDOFF next session traps frozen surface", "NEXT_SESSION_TRAPS"),
    ("C5", "quarterly revenue projection for the Lisbon office", None),
]

svc = RetrievalService.from_profile(VaultProfile(
    root=VAULT, vault_name="Project_in_progress", demoted_prefixes=DEMOTED))

# ---- Gate 1: 5-question recall at the tool's own defaults ----------------
hits, detail = 0, []
c3_rank = None
for name, q, need in CASES:
    out = svc.search(q, output_k=8)          # defaults elsewhere
    paths = out["retrieved_paths"]
    if need is None:
        ok = out["review_required"] is True
        detail.append(f"{name}=OK" if ok else f"{name}=FAIL")
    else:
        r = next((i + 1 for i, p in enumerate(paths) if need in p), None)
        ok = r is not None
        detail.append(f"{name}={'HIT@' + str(r) if r else 'MISS'}")
        if name == "C3":
            c3_rank = r
    hits += bool(ok)
gate1 = hits >= 4

# ---- Gate 2: the specific failing document enters the top 8 -------------
gate2 = c3_rank is not None

# ---- Gate 3: zero-overlap answer stays in the OUTPUT --------------------
tmp = Path(tempfile.mkdtemp())
(tmp / "deep").mkdir()
(tmp / "HANDOFF.md").write_text("unique entry [[bridge]]", encoding="utf-8")
(tmp / "bridge.md").write_text("neutral [[deep/authority]]", encoding="utf-8")
(tmp / "deep" / "authority.md").write_text("zero lexical overlap", encoding="utf-8")
for i in range(30):
    (tmp / f"lexical-{i:03d}.md").write_text(
        f"unique entry noise variant {i} filler-{i}", encoding="utf-8")
zo = RetrievalService.from_profile(
    VaultProfile(root=tmp, obsidian_enabled=False)).search(
        "unique entry", output_k=8, candidate_pool_k=50,
        graph_seed_k=4, max_turns=4)
zo_rank = next((i + 1 for i, p in enumerate(zo["retrieved_paths"])
                if p == "deep/authority.md"), None)
gate3 = zo_rank is not None

# ---- Gate 4: seed sensitivity ------------------------------------------
profile = VaultProfile(root=VAULT, vault_name="Project_in_progress",
                       obsidian_enabled=False, demoted_prefixes=DEMOTED)
corpus = VaultCorpus(profile)
ranks = {}
for gsk in (4, 8, 12, 20):
    out = RecallFirstRetriever(corpus, None).retrieve(
        CASES[2][1], RetrievalConfig(output_k=8, candidate_pool_k=50,
                                     graph_seed_k=gsk, max_turns=6))
    ranks[gsk] = next((i + 1 for i, p in enumerate(out["retrieved_paths"])
                       if "symlink-vs-moc" in p), None)
present = [r for r in ranks.values() if r is not None]
# stable = present at every setting, and spread <= 4 places
gate4 = len(present) == len(ranks) and (max(present) - min(present) <= 4)

print(f"=== D3 gates [{LABEL}] ===")
print(f"  gate1 5-question recall >= 4/5   : {'PASS' if gate1 else 'FAIL'} "
      f"({hits}/5  {' '.join(detail)})")
print(f"  gate2 symlink-vs-moc in top-8    : {'PASS' if gate2 else 'FAIL'} "
      f"(rank {c3_rank})")
print(f"  gate3 zero-overlap in OUTPUT     : {'PASS' if gate3 else 'FAIL'} "
      f"(rank {zo_rank}, 30 lexical competitors)")
print(f"  gate4 seed stability             : {'PASS' if gate4 else 'FAIL'} "
      f"({ranks})")
print(f"  ALL: {'PASS' if all((gate1, gate2, gate3, gate4)) else 'FAIL'}")
