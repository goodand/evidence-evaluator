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


def test_t1_arm_text_matches_the_shipped_docstring_exactly():
    """The load-bearing check. T1 is the arm whose result decides whether the
    tool is safe as shipped -- if this text drifts from server.py, the
    experiment measures a docstring nobody actually uses."""
    normalize = lambda s: " ".join(s.split())  # noqa: E731
    assert normalize(_gen_prompts.T1_DOCSTRING) == normalize(_shipped_docstring()), (
        "T1_DOCSTRING in _gen_prompts.py no longer matches server.py's "
        "registered docstring -- regenerate the manifest as an explicit "
        "amendment commit, do not silently edit the frozen prompts.")


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
    expected = {f"{arm}__{case}" for arm in _gen_prompts.ARMS for case in FIXTURES}
    actual = {p["trial_id"] for p in MANIFEST["prompts"]}
    assert actual == expected


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
