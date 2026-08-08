"""End-to-end check: build a tiny corpus, run a scripted controller through
it, score the resulting trace. Proves the four extracted modules (contract,
runner, evaluator) still work together after being pulled out of the source
experiment -- not just that each one imports.

Run with: cd evidence_evaluator && python3 -m pytest ../tests -q
(sys.path setup below matches the flat-import design; see package README.)
"""

from __future__ import annotations

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "evidence_evaluator"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from contract import CASE_VERSION, GOLD_VERSION, ContractError  # noqa: E402
from evaluator import evaluate  # noqa: E402
from runner import Corpus, run_case  # noqa: E402


@pytest.fixture()
def corpus(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "HANDOFF.md").write_text(
        "# Handoff\n\nSee [the design decision](DESIGN.md) for why.\n",
        encoding="utf-8")
    (docs / "DESIGN.md").write_text(
        "# Design decision\n\nWe chose approach B because approach A leaked "
        "state across runs.\n", encoding="utf-8")
    (docs / "UNRELATED.md").write_text(
        "# Unrelated\n\nNothing to see here.\n", encoding="utf-8")
    return Corpus(docs)


CASE = {
    "contract_version": CASE_VERSION, "id": "T01", "query": "why approach B",
    "condition": "direct-handoff", "handoff_path": "HANDOFF.md",
}
GOLD = {
    "contract_version": GOLD_VERSION, "case_id": "T01",
    "handoff_path": "HANDOFF.md",
    "expected_paths": ["HANDOFF.md", "DESIGN.md"],
    "critical_paths": ["DESIGN.md"],
    "expected_authority": ["DESIGN.md"],
    "claims": [{"claim_id": "c1", "support_ranges": [
        {"path": "DESIGN.md", "start": 1, "end": 4}]}],
    # _terms_hit() treats an empty terms list as vacuously unsatisfiable by
    # design (see evaluator.py's docstring) -- so every one of these needs a
    # real term the passing trace below actually produces.
    "current_state_terms": [["approach"]], "next_action_terms": [["done"]],
    "stop_condition_terms": [["found"]], "is_absent": False,
}


def _scripted_controller(steps):
    it = iter(steps)

    def controller(observation):
        return next(it)
    return controller


def test_full_hard_gate_when_subject_reads_and_cites_correctly(corpus):
    steps = [
        # Query matches HANDOFF.md, not DESIGN.md -- DESIGN.md is only
        # reachable by following the link, which is what the BudgetGuard's
        # "beyond first search" requirement exists to force. `follow_link`'s
        # target is the SOURCE path being expanded (runner.py), so this
        # expands HANDOFF.md's outgoing links to surface DESIGN.md.
        {"action": "reformulate_query", "query": "handoff overview"},
        {"action": "follow_link", "target": "HANDOFF.md"},
        {"action": "read_candidate", "target": "HANDOFF.md", "start": 1, "end": 40},
        {"action": "read_candidate", "target": "DESIGN.md", "start": 1, "end": 40},
        {"action": "answer",
         "answer_text": "Approach B was chosen because A leaked state.",
         "current_state": "found the design decision, approach B chosen",
         "next_action": "done, no further action needed",
         "stop_conditions": ["found the supporting claim"],
         "claims": [{"claim_id": "c1",
                     "support": [{"path": "DESIGN.md", "start": 1, "end": 4}]}]},
    ]
    trace = run_case(CASE, _scripted_controller(steps), corpus, arm="test")
    result = evaluate(trace, GOLD, CASE)
    assert result["failure_codes"] == [], result["failure_meanings"]
    assert result["full_hard_gate"] is True
    assert result["critical_path_recall"] == 1.0


def test_r1_when_critical_path_never_read(corpus):
    steps = [
        {"action": "reformulate_query", "query": "approach B design"},
        {"action": "read_candidate", "target": "HANDOFF.md", "start": 1, "end": 40},
        {"action": "follow_link", "target": "UNRELATED.md"},
        {"action": "answer", "answer_text": "not sure",
         "current_state": "looked around"},
    ]
    trace = run_case(CASE, _scripted_controller(steps), corpus, arm="test")
    result = evaluate(trace, GOLD, CASE)
    assert "R1" in result["failure_codes"]
    assert result["full_hard_gate"] is False


def test_c4_when_citation_path_was_never_read(corpus):
    steps = [
        {"action": "reformulate_query", "query": "handoff overview"},
        # Expands UNRELATED.md (not the citation target) purely to satisfy
        # the BudgetGuard's "beyond first search" exploration requirement --
        # the point of this test is that DESIGN.md, the citation target
        # below, is never read at all.
        {"action": "follow_link", "target": "UNRELATED.md"},
        {"action": "read_candidate", "target": "HANDOFF.md", "start": 1, "end": 5},
        {"action": "answer", "answer_text": "Approach B.",
         "current_state": "approach B chosen",
         "claims": [{"claim_id": "c1",
                     "support": [{"path": "DESIGN.md", "start": 1, "end": 4}]}]},
    ]
    trace = run_case(CASE, _scripted_controller(steps), corpus, arm="test")
    result = evaluate(trace, GOLD, CASE)
    assert "C4" in result["failure_codes"], "cited DESIGN.md without ever reading it"


def test_e1_when_trace_leaks_a_gold_key():
    from contract import validate_trace, TRACE_VERSION
    leaky = {"contract_version": TRACE_VERSION, "arm": "test", "actions": [],
            "reads": [], "critical_paths": ["should not be here"]}
    with pytest.raises(ContractError, match="E1"):
        validate_trace(leaky)


def test_corpus_link_and_mention_resolution(corpus):
    assert corpus.links("HANDOFF.md") == ["DESIGN.md"]
    assert corpus.search("approach B leaked state") == ["DESIGN.md"]
