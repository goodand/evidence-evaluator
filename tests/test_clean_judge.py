"""Regression tests for `run_clean_judge()`'s integrity mechanism.

WHY THIS FILE EXISTS (adversarial review finding C1/#14, 2026-08-09)
-------------------------------------------------------------------
Before this file, **no test called `run_clean_judge` at all**. That absence
is the root cause, not a side note: in the source experiment every caller
(`test_protocol.py`, `run_calibration.py`, `run_smoke.py`,
`run_live_phase_c.py`) always passed `pins=source_hashes()`, so the
always-verify behavior was exercised implicitly. That safety net did not
travel with the extraction, and the shipped default path silently skipped
verification entirely -- a patched evaluator scored clean, exit 0, no
warning.

These tests tamper with the real file on disk and assert on real subprocess
behavior. They are slower than the rest of the suite by design: the thing
under test *is* the subprocess boundary, so mocking it would test nothing.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "evidence_evaluator"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from contract import CASE_VERSION, GOLD_VERSION, TRACE_VERSION  # noqa: E402
from evaluator import run_clean_judge, source_hashes  # noqa: E402

EVALUATOR = PKG / "evaluator.py"

CASE = {"contract_version": CASE_VERSION, "id": "T01", "query": "q",
        "condition": "direct-handoff", "handoff_path": "H.md"}
GOLD = {"contract_version": GOLD_VERSION, "case_id": "T01", "handoff_path": "H.md",
        "expected_paths": ["H.md"], "critical_paths": ["H.md"],
        "expected_authority": ["H.md"],
        "claims": [{"claim_id": "c1",
                   "support_ranges": [{"path": "H.md", "start": 1, "end": 2}]}],
        "is_absent": False}
TRACE = {"contract_version": TRACE_VERSION, "arm": "t", "actions": [],
         "reads": [{"path": "H.md", "start": 1, "end": 2}],
         "claims": [{"claim_id": "c1",
                    "support": [{"path": "H.md", "start": 1, "end": 2}]}],
         "stop_reason": "answer", "answer_text": "ok", "declared_absent": False}


@pytest.fixture()
def payload(tmp_path):
    p = tmp_path / "payload.json"
    p.write_text(json.dumps({"trace": TRACE, "gold": GOLD, "case": CASE}),
                 encoding="utf-8")
    return p


@pytest.fixture()
def tampered_evaluator():
    """Replace evaluate()'s body with an always-pass stub, on the real file,
    then restore. Yields the pins captured BEFORE tampering -- i.e. pins from
    a trusted context, which is the only kind that proves anything."""
    import re
    original = EVALUATOR.read_bytes()
    trusted_pins = source_hashes()
    src = original.decode("utf-8")
    match = re.search(r"^def evaluate\(.*?\) -> dict:\n", src, re.M)
    start = match.end()
    nxt = re.search(r"^\n\n# -+\n# clean judge", src[start:], re.M)
    stub = ('    """TAMPERED BY TEST"""\n'
            '    return {"full_hard_gate": True, "TAMPERED": True}\n')
    EVALUATOR.write_bytes((src[:start] + stub + src[start + nxt.start():]).encode("utf-8"))
    try:
        yield trusted_pins
    finally:
        EVALUATOR.write_bytes(original)


def test_trusted_pins_reject_a_patched_evaluator(payload, tampered_evaluator):
    """The mechanism's whole purpose. Must fail loudly, not score."""
    result = run_clean_judge(payload, pins=tampered_evaluator)
    assert "judge_error" in result, f"tampered evaluator scored anyway: {result}"
    assert "drifted" in result["judge_error"]
    assert result.get("returncode") == 3
    assert "TAMPERED" not in json.dumps(result)


def test_without_pins_the_result_is_marked_unverified(payload, tampered_evaluator):
    """No trusted pins means no integrity claim can be made. The score still
    runs, but it must be *labelled* -- the C1 bug was that it looked exactly
    like a verified run."""
    result = run_clean_judge(payload)
    assert result.get("integrity_verified") is False, (
        "an unverified run must say so; C1 was that it was indistinguishable "
        "from a verified one")


def test_verified_runs_are_marked_verified(payload):
    """The other direction: a real verified run must be positively marked, or
    `integrity_verified` would be a field that is only ever False and thus
    carries no information."""
    result = run_clean_judge(payload, pins=source_hashes())
    assert "judge_error" not in result, result
    assert result.get("integrity_verified") is True


def test_locally_computed_pins_would_be_vacuous(payload, tampered_evaluator):
    """Pins the *caller* to the specific mistake this fix avoided.

    The first attempted C1 fix was `pins = pins or source_hashes()` inside
    run_clean_judge. This test demonstrates why that is worse than the bug:
    hashes read at call time come from the already-patched file, so they
    match, drift is empty, and the check passes -- a guard that cannot fail.
    If someone reintroduces that 'fix', this test documents what it buys.
    """
    pins_read_after_tampering = source_hashes()
    assert pins_read_after_tampering != tampered_evaluator, (
        "sanity: the tampered file must hash differently than the trusted pins")

    result = run_clean_judge(payload, pins=pins_read_after_tampering)
    assert "judge_error" not in result, (
        "locally-computed pins are expected to pass vacuously -- that is the "
        "point of this test")
    assert result.get("TAMPERED") is True, (
        "and the tampered scorer's output goes through unchallenged, which is "
        "why pins must come from a trusted context")


def test_verify_self_without_pins_is_refused_not_skipped():
    """The CLI-level half of the fix. `--verify-self` with no `--pins` used to
    fall through and score; it must now be an error, because a flag named
    'verify' that silently verifies nothing is a lie."""
    import subprocess
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"trace": TRACE, "gold": GOLD, "case": CASE}, f)
        path = f.name
    with tempfile.TemporaryDirectory() as cache:
        proc = subprocess.run(
            [sys.executable, "-B", "-E", "-P", "-I", "-X", f"pycache_prefix={cache}",
             str(EVALUATOR), "--payload", path, "--verify-self"],
            capture_output=True, text=True, env={"PATH": ""}, cwd=PKG)
    assert proc.returncode == 5, (
        f"expected refusal (exit 5), got {proc.returncode}: {proc.stdout[:200]}")
    assert "requires --pins" in proc.stderr
