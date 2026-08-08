"""Protocol self-verification: the frozen design, the harness code, and the
shipped tool must agree. Catches the drift this repo has been bitten by --
a preregistration that describes one thing while the code measures another.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent.parent / "vault_backlinks_mcp"))

import pytest  # noqa: E402

import _gen_prompts  # noqa: E402
from evaluate import CASE_TRUTH, FAILURE_CODES, score_one, validate_trial_set  # noqa: E402

FIXTURES = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
MANIFEST = json.loads((HERE / "_prompts.json").read_text(encoding="utf-8"))


def _shipped_docstring() -> str:
    """Read server.py's registered docstring from SOURCE, via AST.

    Deliberately not `import server` -- that pulls in `fastmcp`, an optional
    dependency. Importing would make this check BLOCKED (unable to run) on
    any machine without fastmcp installed, and this workspace's gate contract
    is explicit that BLOCKED is neither pass nor fail: it is a check that did
    not happen. This check is load-bearing enough that it must actually run
    everywhere, so it parses the file instead.
    """
    import ast
    src = (HERE.parent.parent / "vault_backlinks_mcp" / "server.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "vault_backlinks":
            doc = ast.get_docstring(node)
            if doc:
                return doc
    raise AssertionError("could not find vault_backlinks' docstring in server.py")


_NORMALIZE = lambda s: " ".join(s.split())  # noqa: E731

# T1_DOCSTRING's frozen hash (recorded 2026-08-09, when T3 was introduced and
# T1 stopped tracking server.py). Any change to this constant must be an
# explicit amendment, not a silent edit -- 609a8bb's scored trials depend on
# this exact text.
_T1_FROZEN_SHA256 = "81f9cc4868f5a100485afeaf08544b57578efb33779d369e9cf07870dd03f0f8"


def test_t1_docstring_is_frozen_and_no_longer_tracks_server_py():
    """T1 is baked into the already-scored, committed manifest (857b203) and
    trials.json (609a8bb) -- it must stay byte-identical forever regardless
    of what server.py's docstring becomes later. This replaces the earlier
    "T1 matches shipped" check (see test_t3_arm_text_matches_the_shipped_docstring_exactly
    below) now that T1 and "shipped" have diverged on purpose."""
    import hashlib
    got = hashlib.sha256(_gen_prompts.T1_DOCSTRING.encode("utf-8")).hexdigest()
    assert got == _T1_FROZEN_SHA256, (
        "T1_DOCSTRING changed -- this would silently redefine what the "
        "already-scored T1 trials (609a8bb) measured. If T1 genuinely needs "
        "to change, that is a new arm, not an edit to this one.")


def test_t3_arm_text_matches_the_shipped_docstring_exactly():
    """The load-bearing check, now pointed at T3 -- the 2026-08-09 candidate
    fix applied to server.py (OPERATIONS_LOG.md §5 item 2 / §6). If this
    drifts, the T3 experiment measures a docstring nobody actually ships."""
    assert _NORMALIZE(_gen_prompts.T3_DOCSTRING) == _NORMALIZE(_shipped_docstring()), (
        "T3_DOCSTRING in _gen_prompts.py no longer matches server.py's "
        "registered docstring -- regenerate _prompts_t3.json as an explicit "
        "amendment, do not silently edit frozen prompts.")


def test_every_fixture_has_a_scored_truth_entry():
    assert set(FIXTURES) == set(CASE_TRUTH), (
        "fixtures.json and evaluate.CASE_TRUTH must cover the same cases")


def test_fixtures_are_real_server_output_shape():
    for case, resp in FIXTURES.items():
        assert resp["contract_version"] == "vault-backlinks-result-v1", case
        for key in ("backend_used", "backlinks", "total", "dropped_out_of_scope",
                    "review_required", "review_checks", "error"):
            assert key in resp, f"{case} missing {key}"


def test_the_confusable_trio_really_is_confusable():
    """The experiment's premise, asserted rather than assumed: A, B and C all
    carry total == 0 while meaning three different things. If a future change
    to the server makes them distinguishable by `total` alone, this
    experiment's rationale is void and the preregistration must be revisited."""
    assert FIXTURES["A_backend_failure"]["total"] == 0
    assert FIXTURES["B_genuine_zero"]["total"] == 0
    assert FIXTURES["C_all_out_of_scope"]["total"] == 0
    assert FIXTURES["A_backend_failure"]["error"] is not None
    assert FIXTURES["B_genuine_zero"]["error"] is None
    assert FIXTURES["C_all_out_of_scope"]["dropped_out_of_scope"] > 0


def test_manifest_covers_every_arm_case_combination():
    """Scoped to the originally-frozen arms (T0/T1/T2) -- T3 lives in its
    own addendum manifest (_prompts_t3.json), checked separately below, so
    it must not be pulled into ARMS's full membership here."""
    original_arms = ("T0", "T1", "T2")
    expected = {f"{arm}__{case}" for arm in original_arms for case in FIXTURES}
    actual = {p["trial_id"] for p in MANIFEST["prompts"]}
    assert actual == expected


def test_t3_addendum_manifest_covers_only_its_designated_cases():
    """T3 exists to re-test only the two cells where T1/T2 actually failed
    (B_genuine_zero: Z2, D_real_hits_with_review: Z6) -- not a full re-run.
    See ARM_CASES's docstring in _gen_prompts.py.

    Calls build() directly rather than reading the pre-generated
    _prompts_t3.json -- mutation-verified 2026-08-09: an earlier version of
    this test read the static file, and gutting ARM_CASES filtering in
    build() left it green because the file on disk didn't change when the
    *code* was mutated. Exercising the live function is what makes this
    catch a real regression instead of a stale artifact.
    """
    t3_manifest = _gen_prompts.build("test-commit", arms=("T3",))
    actual = {p["trial_id"] for p in t3_manifest["prompts"]}
    assert actual == {"T3__B_genuine_zero", "T3__D_real_hits_with_review"}

    if (HERE / "_prompts_t3.json").is_file():
        on_disk = json.loads((HERE / "_prompts_t3.json").read_text(encoding="utf-8"))
        on_disk_ids = {p["trial_id"] for p in on_disk["prompts"]}
        assert on_disk_ids == actual, (
            "_prompts_t3.json on disk does not match build()'s current "
            "output -- regenerate it (python3 _gen_prompts.py <design_commit> "
            "--arms T3 --out _prompts_t3.json)")


def test_manifest_prompt_hashes_are_correct():
    import hashlib
    for p in MANIFEST["prompts"]:
        want = hashlib.sha256(p["prompt"].encode("utf-8")).hexdigest()
        assert p["prompt_sha256"] == want, f"{p['trial_id']} hash mismatch"


def test_arms_differ_only_by_the_interface_block():
    """Methodology §8: the task text must be identical across arms, or the
    manipulation is confounded with instruction wording."""
    by_case = {}
    for p in MANIFEST["prompts"]:
        by_case.setdefault(p["case"], []).append(p)
    for case, rows in by_case.items():
        tails = {r["prompt"].split("\n\n---\n\n", 1)[1] for r in rows}
        assert len(tails) == 1, f"{case}: task text differs across arms"


def test_arm_interfaces_are_strictly_nested():
    """T0 subset of T1 subset of T2 -- the manipulation is added information,
    not different information."""
    assert _gen_prompts.ARMS["T0"] in _gen_prompts.ARMS["T1"]
    assert _gen_prompts.ARMS["T1"] in _gen_prompts.ARMS["T2"]


def test_task_text_does_not_leak_the_answer():
    """The prompt must not tell the subject that failure is possible or that
    zero is expected -- that would manufacture the behaviour being measured."""
    task = _gen_prompts.TASK.lower()
    for leak in ("fail", "error", "zero", "unavailable", "cannot", "uncertain"):
        assert leak not in task, f"task text leaks {leak!r}"


@pytest.mark.parametrize("code", sorted(FAILURE_CODES))
def test_every_declared_failure_code_is_reachable(code):
    """No documented-but-unreachable codes -- the same rule this workspace
    applies to guards (a code nothing can emit is a silent cap)."""
    probes = [
        {"case": "A_backend_failure",
         "response": {"backlink_count": 0, "certain": True, "caveats": ["x"]}},
        {"case": "B_genuine_zero",
         "response": {"backlink_count": None, "certain": False, "caveats": ["x"]}},
        {"case": "D_real_hits_with_review",
         "response": {"backlink_count": 4, "certain": True, "caveats": []}},
        {"case": "D_real_hits_with_review",
         "response": {"backlink_count": 9, "certain": True, "caveats": ["x"]}},
        {"case": "B_genuine_zero", "response": "not a dict"},
        {"case": "D_real_hits_with_review",
         "response": {"backlink_count": 4, "certain": False, "caveats": ["x"]}},
    ]
    assert any(code in score_one(p) for p in probes), (
        f"{code} ({FAILURE_CODES[code]}) is declared but no probe reaches it")


def test_provenance_refuses_a_mismatched_prompt_hash():
    trials = {
        "protocol": dict(MANIFEST["protocol"]),
        "trials": [{
            "trial_id": MANIFEST["prompts"][0]["trial_id"],
            "prompt_sha256": "0" * 64,
            "execution": {"context_isolation": "workflow_cold_subagent",
                          "tool_access": "description_only"},
        }],
    }
    errors = validate_trial_set(trials, MANIFEST)
    assert any("hash differs" in e for e in errors)


def test_provenance_refuses_a_wrong_tool_access_label():
    """E2.2 used tool_access=schema_only for a different manipulation. A trial
    set carrying that label is not this experiment and must be refused."""
    trials = {
        "protocol": dict(MANIFEST["protocol"]),
        "trials": [{
            "trial_id": MANIFEST["prompts"][0]["trial_id"],
            "prompt_sha256": MANIFEST["prompts"][0]["prompt_sha256"],
            "execution": {"context_isolation": "workflow_cold_subagent",
                          "tool_access": "schema_only"},
        }],
    }
    errors = validate_trial_set(trials, MANIFEST)
    assert any("tool_access" in e for e in errors)


def test_manifest_is_frozen_against_a_real_commit():
    """Guards the freeze order (methodology §1). Was
    `assert design_commit == "PENDING_FREEZE"` until the manifest-freeze
    commit filled it in -- updated here, in that same commit, deliberately.
    Now guards the opposite direction: design_commit must be a real,
    40-hex-char commit id, not a placeholder and not something hand-typed."""
    import re
    design_commit = MANIFEST["protocol"]["design_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", design_commit), (
        f"design_commit {design_commit!r} is not a real git commit hash")
