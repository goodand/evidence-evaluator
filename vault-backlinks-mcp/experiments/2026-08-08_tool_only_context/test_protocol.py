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


# T3_DOCSTRING's frozen hash (recorded 2026-08-09, when the adversarial
# review's C2 finding forced server.py's docstring to change and T3 stopped
# tracking it). trials_t3.json (296e56a) was measured against this exact
# text -- see test_t3_docstring_is_frozen below.
_T3_FROZEN_SHA256 = "8bde800502dde96b7d4f13beef1a23dae085b60d2a8c497fe49cafed1c0dd977"


def test_t3_docstring_is_frozen_and_no_longer_tracks_server_py():
    """Same rule as T1, now applied to T3.

    T3 was the shipped text when trials_t3.json was collected. The 2026-08-09
    adversarial review then found that this very text instructs agents to read
    `backlink_count`, a field the tool never returns (finding C2 -- the name
    was copied from the experiment's own RESPONSE_SCHEMA). Fixing server.py to
    say `total` means the shipped docstring and T3 have diverged **on
    purpose**: T3 must stay byte-identical because it is what the scored
    trials actually measured.

    Consequence recorded honestly rather than papered over: T3's reported
    improvement (OPERATIONS_LOG §7) was measured against a docstring
    containing a wrong field name. Whether that invalidates the result is a
    judgement for the ops-doc, not something to silently fix by editing the
    frozen prompt.
    """
    import hashlib
    got = hashlib.sha256(_gen_prompts.T3_DOCSTRING.encode("utf-8")).hexdigest()
    assert got == _T3_FROZEN_SHA256, (
        "T3_DOCSTRING changed -- this would silently redefine what the "
        "already-scored T3 trials (296e56a) measured. If the shipped "
        "docstring needs to change, that is a new arm (T4), not an edit.")


def test_shipped_docstring_does_not_reference_a_nonexistent_field():
    """The load-bearing check, re-pointed at the *property* that C2 violated
    rather than at any one arm's text.

    C2 (2026-08-09, two reviewers converged independently): server.py's
    docstring told agents to read `backlink_count`; the tool's actual keys are
    `backlinks` (list) and `total` (int). Verified at the time by grep (only
    matched the docstring) and by executing the pipeline. Pinning arm text
    would not have caught this -- the arm text *was* the shipped text and both
    were wrong together. This asserts against contracts.py's real output keys
    instead.
    """
    shipped = _shipped_docstring()
    import re
    referenced = set(re.findall(r"`(\w+)`", shipped))

    import contracts
    from registry import VaultEntry
    import inspect
    error_src = inspect.getsource(contracts._error_result)
    real_keys = set(re.findall(r'"(\w+)":', error_src))

    # Field-like names the docstring cites that the result never carries.
    # Allowlist: values and prose terms, not result keys.
    allowed_non_keys = {"live", "none", "vault_id", "path", "max_results",
                        "required_action", "backlink_count_IS_NOT_A_KEY"}
    cited_fields = {r for r in referenced
                    if r.islower() and "_" in r or r in {"total", "error", "backlinks"}}
    bogus = {f for f in cited_fields if f not in real_keys and f not in allowed_non_keys}
    assert not bogus, (
        f"server.py's docstring cites field(s) the tool never returns: "
        f"{sorted(bogus)}. Real keys: {sorted(real_keys)}")


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
