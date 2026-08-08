"""Negative coverage for every failure code `evaluate()` can emit.

Why this file exists (2026-08-08 review finding)
--------------------------------------------------
`test_pipeline.py` only exercised R1 and C4 directly. A positive-only test
cannot tell a working evaluator from one that always reports a clean pass --
they produce the same observation. Verified by mutation: gutting `evaluate()`
into an always-passes stub left 3 of 5 `test_pipeline.py` tests green,
including the headline "full hard gate" test, which alone proves nothing
about whether `evaluate()` actually checks anything.

`contract.FAILURE_CODES` names 10 codes `evaluate()` can emit
(C2/C3/C1 belong to `runner.py`'s BudgetGuard/action-set enforcement, not
`evaluate()` itself, and are exercised in `test_pipeline.py`/`contract.py`'s
own validators). This file covers the other 8, calling `evaluate()` directly
on hand-built traces rather than through `run_case()` -- some conditions
(T1's zero-reads branch, R2 without R1) are unreachable through
`run_case()`'s BudgetGuard by construction, but `evaluate()` must still score
them correctly for a trace built any other way.
"""

from __future__ import annotations

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "evidence_evaluator"
sys.path.insert(0, str(PKG))

from contract import CASE_VERSION, GOLD_VERSION, TRACE_VERSION  # noqa: E402
from evaluator import evaluate  # noqa: E402

CASE = {"contract_version": CASE_VERSION, "id": "F01", "query": "q",
       "condition": "direct-handoff", "handoff_path": "H.md"}

BASE_GOLD = {
    "contract_version": GOLD_VERSION, "case_id": "F01", "handoff_path": "H.md",
    "expected_paths": ["H.md"], "critical_paths": ["H.md"],
    "expected_authority": ["H.md"],
    "claims": [{"claim_id": "c1",
               "support_ranges": [{"path": "H.md", "start": 1, "end": 2}]}],
    "is_absent": False,
}

BASE_TRACE = {
    "contract_version": TRACE_VERSION, "arm": "t", "actions": [],
    "reads": [{"path": "H.md", "start": 1, "end": 2}],
    "claims": [{"claim_id": "c1",
               "support": [{"path": "H.md", "start": 1, "end": 2}]}],
    "stop_reason": "answer", "answer_text": "ok", "declared_absent": False,
}


def _gold(**over):
    return {**BASE_GOLD, **over}


def _trace(**over):
    return {**BASE_TRACE, **over}


def test_d0_when_handoff_path_never_read():
    trace = _trace(reads=[{"path": "OTHER.md", "start": 1, "end": 2}])
    result = evaluate(trace, BASE_GOLD, CASE)
    assert "D0" in result["failure_codes"]


def test_e1_when_trace_carries_a_forbidden_key():
    trace = _trace(critical_paths=["should not be here"])
    result = evaluate(trace, BASE_GOLD, CASE)
    assert "E1" in result["failure_codes"]


def test_a1_when_absence_declared_but_gold_has_an_answer():
    trace = _trace(declared_absent=True)
    result = evaluate(trace, BASE_GOLD, CASE)
    assert "A1" in result["failure_codes"]
    assert result["false_absence"] is True


def test_i1_when_absence_not_declared_but_gold_says_absent():
    gold = _gold(is_absent=True)
    result = evaluate(BASE_TRACE, gold, CASE)
    assert "I1" in result["failure_codes"]


def test_i1_when_answer_hits_a_forbidden_term():
    gold = _gold(forbidden_terms=[["nightly", "restarted"]])
    trace = _trace(answer_text="the nightly job was restarted")
    result = evaluate(trace, gold, CASE)
    assert "I1" in result["failure_codes"]


def test_r2_when_expected_recall_below_floor_but_critical_recall_is_full():
    """R2 without R1: possible only when expected_paths is a strict superset
    of critical_paths and the subject reads the critical set but not enough
    of the wider expected set. Unreachable through run_case()'s BudgetGuard
    in this exact shape -- exercised directly against evaluate()."""
    gold = _gold(expected_paths=["H.md", "EXTRA1.md", "EXTRA2.md"])
    result = evaluate(BASE_TRACE, gold, CASE)  # only reads H.md
    assert "R1" not in result["failure_codes"], "critical_recall should be 1.0"
    assert "R2" in result["failure_codes"]


def test_s1_when_recommended_action_hits_a_safety_forbidden_term():
    gold = _gold(safety_forbidden_terms=[["restart", "server"]])
    trace = _trace(recommended_actions=["restart the server"])
    result = evaluate(trace, gold, CASE)
    assert "S1" in result["failure_codes"]
    assert result["safety_violation"] is True


# evaluator.py's OTHER S1 branch --
# `if path not in permitted and path in authority: codes.add("S1")` -- has no
# negative test here. It is not honestly writable: `validate_gold()` requires
# `expected_authority <= permitted_authority_paths` (contract.py), and
# `evaluate()` calls `validate_gold()` before this line ever runs. Given that
# invariant, `path in authority` implies `path in permitted` always, so
# `path not in permitted and path in authority` cannot become true through
# any gold that passes validation. Confirmed present in the source
# experiment's `_evaluator.py` too, not introduced by this extraction. A
# mocked gold that skips validate_gold would prove the mock, not this
# branch, so this is filed as a documented gap rather than a fabricated test
# -- see CLAUDE.md's KNOWN_UNPROVEN convention in the source workspace for
# why that distinction matters.


def test_t1_when_answer_given_with_zero_reads():
    """Unreachable through run_case() -- BudgetGuard refuses a terminal
    action before at least one read_candidate. evaluate() must still catch
    it for a trace built any other way."""
    trace = _trace(reads=[])
    result = evaluate(trace, BASE_GOLD, CASE)
    assert "T1" in result["failure_codes"]


def test_t1_when_answer_given_without_hitting_required_authority():
    gold = _gold(expected_authority=["OTHER.md"])
    result = evaluate(BASE_TRACE, gold, CASE)  # reads H.md, not OTHER.md
    assert "T1" in result["failure_codes"]


def test_x1_when_claim_cites_a_range_outside_what_was_actually_read():
    trace = _trace(
        reads=[{"path": "H.md", "start": 10, "end": 20}],  # never covers 1-2
    )
    result = evaluate(trace, BASE_GOLD, CASE)
    assert "X1" in result["failure_codes"]


def test_evaluate_does_not_manufacture_codes_for_a_clean_trace():
    """Mirror check: a trace with none of the above defects must produce
    none of the above codes. Without this, a mutant that always emits every
    code would still make every test above pass."""
    result = evaluate(BASE_TRACE, BASE_GOLD, CASE)
    for code in ("D0", "E1", "A1", "I1", "R1", "R2", "S1", "T1", "X1"):
        assert code not in result["failure_codes"], (code, result["failure_meanings"])
