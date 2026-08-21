"""The separation dataset: every code fires on its own world, and stays quiet
on a clean one.

This mirrors the Validation section of
`.vault-harness/vault-md-retrieval/AGENT_TOOL.md`, which establishes its
exception classes the same way -- six cases return `complete`, and two named
classes each fire on the case built to trigger them. A harness that reports
review codes it has never been shown emitting is the vacuous guard it exists to
prevent, so the codes and this file are checked against each other below.

WHAT THIS FILE TESTS AND WHAT IT DOES NOT
-----------------------------------------
It tests the HARNESS: that each check reaches the right verdict on a world
built for it, that a check which cannot run is reported as skipped rather than
silently dropped, and that a clean repository comes back `complete`.

It does NOT re-test the order-independence checker's detection ability. That
tool has its own poison test, run against the genuine pre-fix tree
(vault-backlinks-mcp 95aefdb under VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0, where
it named FILESYSTEM_FALLBACK_USED as passing in the suite and failing alone).
Here the harness's job is only to relay that tool's verdict, so a stub with the
right exit code is the honest fixture -- and `test_order_dependence_is_relayed`
says so rather than implying detection was proven twice.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parent / "selftest_agent_tool.py"

sys.path.insert(0, str(HARNESS.parent))
from selftest_agent_tool import REQUIRED_ACTIONS  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


def _repo(tmp_path: Path, *, passing: bool = True, extra: dict[str, str] | None = None,
          commit: bool = True) -> Path:
    """A minimal repository the harness can audit."""
    repo = tmp_path / "subject"
    (repo / "tests").mkdir(parents=True)
    body = "def test_ok():\n    assert True\n" if passing else \
           "def test_broken():\n    assert False\n"
    (repo / "tests" / "test_basic.py").write_text(body, encoding="utf-8")
    for rel, content in (extra or {}).items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if path.suffix == ".py" and "scripts" in rel:
            path.chmod(0o755)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "harness@test.local")
    _git(repo, "config", "user.name", "harness")
    if commit:
        _git(repo, "add", "-A")
        _git(repo, "commit", "-q", "-m", "fixture")
    return repo


def run_harness(repo: Path, *args: str) -> dict:
    proc = subprocess.run([sys.executable, str(HARNESS), str(repo), *args],
                          capture_output=True, text=True)
    assert proc.stdout.strip(), f"harness produced no output; stderr={proc.stderr}"
    return json.loads(proc.stdout)


def codes(result: dict) -> set[str]:
    return {check["code"] for check in result["review_checks"]}


def skipped(result: dict) -> set[str]:
    return {check.get("skipped_check") for check in result["review_checks"]
            if check["code"] == "CHECK_DID_NOT_RUN"}


# --- the negative witness -------------------------------------------------

CLEAN_ARGS = ("--env", "SELFTEST_HARNESS_UNUSED=1",
              "--guard-source", "src/guards.py",
              "--guard-registry", "tests/test_witness.py")

CLEAN_FILES = {
    "src/guards.py": '_GUARDS = [{"code": "SOMETHING_ODD"}]\n',
    "tests/test_witness.py": '# witness for SOMETHING_ODD\ndef test_w():\n    assert True\n',
    "scripts/order_independence_check.py": "import sys\nsys.exit(0)\n",
}


ITEMWISE_PYTHON = os.environ.get("SELFTEST_ITEMWISE_PYTHON")
"""An interpreter that can import pytest_randomly.

The within-file ordering check needs one, and this repository deliberately does
NOT take pytest-randomly as a hard dependency -- absence must degrade to
CHECK_DID_NOT_RUN, which is itself one of the cases below. So the firing case
needs an interpreter supplied from outside:

    python3 -m venv /tmp/itemwise && /tmp/itemwise/bin/pip install pytest pytest-randomly
    SELFTEST_ITEMWISE_PYTHON=/tmp/itemwise/bin/python python3 -m pytest selftest-harness/

When it is unset, `test_itemwise_fires_on_same_file_pollution` FAILS rather than
skipping. A skipped witness and a passing witness must not look alike -- that is
the whole subject of this file.
"""


def test_a_clean_repository_comes_back_complete(tmp_path):
    """Without this, a harness that fired on everything would satisfy every
    other test in this file.

    `--python` is supplied so the within-file ordering check can actually run;
    otherwise this fixture is legitimately `review_required` for a missing
    plugin, which is a different case (see
    `test_itemwise_reports_a_missing_plugin_as_a_skip`).
    """
    if not ITEMWISE_PYTHON:
        pytest.fail(
            "SELFTEST_ITEMWISE_PYTHON is unset, so the clean case cannot be "
            "distinguished from a case where a check merely could not run. "
            "See the ITEMWISE_PYTHON docstring for the one-line setup."
        )
    repo = _repo(tmp_path, extra=CLEAN_FILES)
    result = run_harness(repo, *CLEAN_ARGS, "--python", ITEMWISE_PYTHON)
    assert result["status"] == "complete", (
        f"a clean repository produced review codes {codes(result)}: "
        f"{result['review_checks']}"
    )
    assert not result["checks_skipped"], (
        f"nothing should have been skipped here: {result['checks_skipped']}"
    )


def test_itemwise_fires_on_same_file_pollution(tmp_path):
    """The case the file-level checker structurally cannot cover.

    Two tests in ONE file, victim defined first so the suite is GREEN in
    definition order and nobody notices. Measured: the delegated file-level
    checker reports OK on exactly this shape, while pytest-randomly surfaced it
    on 25 of 40 random seeds. The pinned seeds were chosen from that hit set, so
    them firing here is by construction, not evidence about unseen defects.
    """
    if not ITEMWISE_PYTHON:
        pytest.fail(
            "SELFTEST_ITEMWISE_PYTHON is unset, so ORDER_DEPENDENT_ITEMWISE has "
            "no positive witness in this run. Refusing to report a pass for a "
            "code nobody has seen fire."
        )
    files = dict(CLEAN_FILES)
    files["tests/test_basic.py"] = (
        "_STATE = {'dirty': False}\n\n"
        "def test_a_needs_a_clean_state():\n"
        "    assert not _STATE['dirty']\n\n"
        "def test_b_pollutes():\n"
        "    _STATE['dirty'] = True\n")
    repo = _repo(tmp_path, extra=files)

    baseline = subprocess.run(
        [ITEMWISE_PYTHON, "-m", "pytest", "tests/", "-q", "--color=no",
         "-p", "no:randomly"], cwd=repo, capture_output=True, text=True)
    # Asserting "no failures" rather than a test count: the first version
    # asserted "2 passed" and the fixture actually has three tests, because
    # CLEAN_FILES contributes one of its own. A count is a second fact to keep
    # in sync; the property that matters is only that nothing fails.
    assert "failed" not in baseline.stdout, (
        "the fixture is supposed to be GREEN in definition order, otherwise it "
        f"is just a failing suite: {baseline.stdout[-400:]}"
    )

    result = run_harness(repo, "--guard-source", "src/guards.py",
                         "--guard-registry", "tests/test_witness.py",
                         "--python", ITEMWISE_PYTHON)
    assert "ORDER_DEPENDENT_ITEMWISE" in codes(result), (
        f"within-file pollution went unreported: {result['review_checks']}"
    )
    evidence = next(c for c in result["review_checks"]
                    if c["code"] == "ORDER_DEPENDENT_ITEMWISE")["evidence"]
    by_order = evidence["disagreements"][0]["outcomes_by_order"]
    assert by_order["-p no:randomly"] == "PASSED", (
        "the report must show that definition order passes -- that is what "
        "makes this defect invisible without shuffling"
    )
    assert "FAILED" in by_order.values()


def test_itemwise_reports_a_missing_plugin_as_a_skip(tmp_path):
    """Absence of pytest-randomly must degrade to CHECK_DID_NOT_RUN, never to a
    quiet pass. This is what keeps the plugin an optional dependency without the
    optionality turning into a blind spot."""
    repo = _repo(tmp_path, extra=CLEAN_FILES)
    # A path that is not an interpreter at all. Deterministic and
    # environment-independent: it works whether or not this machine happens to
    # have pytest-randomly installed anywhere.
    result = run_harness(repo, "--guard-source", "src/guards.py",
                         "--guard-registry", "tests/test_witness.py",
                         "--python", str(tmp_path / "no-such-interpreter"))
    assert "ORDER_DEPENDENT_ITEMWISE" in skipped(result), (
        f"a missing plugin was not reported as a skip: {result['review_checks']}"
    )
    assert "ORDER_DEPENDENT_ITEMWISE" not in result["checks_run"]


# --- one positive witness per code ----------------------------------------

def test_suite_not_green_fires_on_a_failing_test(tmp_path):
    repo = _repo(tmp_path, passing=False, extra=CLEAN_FILES)
    result = run_harness(repo, *CLEAN_ARGS)
    assert "SUITE_NOT_GREEN" in codes(result)


def test_worktree_dirty_fires_on_an_uncommitted_change(tmp_path):
    repo = _repo(tmp_path, extra=CLEAN_FILES)
    (repo / "tests" / "stray_debris.py").write_text("x = 1\n", encoding="utf-8")
    result = run_harness(repo, *CLEAN_ARGS)
    assert "WORKTREE_DIRTY" in codes(result)


def test_guard_without_witness_fires_when_the_registry_omits_a_code(tmp_path):
    files = dict(CLEAN_FILES)
    files["src/guards.py"] = ('_GUARDS = [{"code": "SOMETHING_ODD"},\n'
                              '           {"code": "STALE_INDEX_V2"}]\n')
    repo = _repo(tmp_path, extra=files)
    result = run_harness(repo, *CLEAN_ARGS)
    assert "GUARD_WITHOUT_WITNESS" in codes(result)
    evidence = next(c for c in result["review_checks"]
                    if c["code"] == "GUARD_WITHOUT_WITNESS")["evidence"]
    assert evidence["missing"] == ["STALE_INDEX_V2"]


def test_a_guard_code_containing_a_digit_is_not_invisible(tmp_path):
    """The narrower `[A-Z_]+` class skipped digit-bearing codes entirely, so the
    completeness check went vacuous for exactly the guards it exists to catch
    (vault-backlinks-mcp 95aefdb). This pins the widened class."""
    files = dict(CLEAN_FILES)
    files["src/guards.py"] = '_GUARDS = [{"code": "V2_ONLY"}]\n'
    files["tests/test_witness.py"] = "def test_w():\n    assert True\n"
    repo = _repo(tmp_path, extra=files)
    result = run_harness(repo, *CLEAN_ARGS)
    assert "GUARD_WITHOUT_WITNESS" in codes(result), (
        "a guard code containing a digit was not seen at all"
    )


def test_a_code_that_only_appears_in_prose_is_not_counted_as_a_guard(tmp_path):
    """Precision of the AST swap, which the regex did not have.

    The replaced regex matched `"code": "X"` anywhere in the file, including
    inside docstrings and comments. Measured on a probe: regex found three
    codes, the parse found one. That mattered in the direction nobody checks --
    a registry could satisfy the completeness check by naming a code that only
    ever appeared in a comment, so the check would report coverage of a guard
    that does not exist.

    Here the registry names ONLY the real guard. Under the old regex the two
    prose codes would have been reported as missing witnesses; under the parse
    they are not guards at all and the check is quiet.
    """
    files = dict(CLEAN_FILES)
    files["src/guards.py"] = (
        '"""Module docstring mentioning {"code": "DOCUMENTED_BUT_NOT_REAL"}."""\n'
        '# A commented-out guard: {"code": "COMMENTED_OUT"}\n'
        '_GUARDS = [{"code": "THE_ONLY_REAL_ONE"}]\n')
    files["tests/test_witness.py"] = (
        "# witness for THE_ONLY_REAL_ONE\n"
        "def test_w():\n    assert True\n")
    repo = _repo(tmp_path, extra=files)
    result = run_harness(repo, "--guard-source", "src/guards.py",
                         "--guard-registry", "tests/test_witness.py")
    assert "GUARD_WITHOUT_WITNESS" not in codes(result), (
        "a code appearing only in a docstring or comment was treated as a "
        f"guard: {result['review_checks']}"
    )


def test_env_sensitive_fires_when_import_time_configuration_changes_outcomes(tmp_path):
    files = dict(CLEAN_FILES)
    files["tests/test_basic.py"] = (
        "import os\n"
        "# read at import, exactly like contracts.py reads its fallback switch\n"
        "_ON = os.environ.get('SELFTEST_HARNESS_SWITCH', '1') != '0'\n"
        "def test_depends_on_the_environment():\n"
        "    assert _ON\n"
    )
    repo = _repo(tmp_path, extra=files)
    result = run_harness(
        repo, "--env", "SELFTEST_HARNESS_SWITCH=0",
        "--guard-source", "src/guards.py",
        "--guard-registry", "tests/test_witness.py")
    assert "ENV_SENSITIVE" in codes(result)
    evidence = next(c for c in result["review_checks"]
                    if c["code"] == "ENV_SENSITIVE")["evidence"]
    assert evidence["differences"][0]["default"] == "PASSED"
    assert evidence["differences"][0]["under_env"] == "FAILED"


def test_order_dependence_is_relayed_from_the_repos_own_checker(tmp_path):
    """Relay only. The checker's ability to DETECT order dependence is proven by
    its own poison test against the pre-fix tree, not here -- see this file's
    docstring. What this pins is that a non-zero verdict is not swallowed."""
    files = dict(CLEAN_FILES)
    files["scripts/order_independence_check.py"] = (
        "import sys\nprint('ORDER-DEPENDENT: 1 test(s)')\nsys.exit(1)\n")
    repo = _repo(tmp_path, extra=files)
    result = run_harness(repo, *CLEAN_ARGS)
    assert "ORDER_DEPENDENT" in codes(result)


def test_order_dependence_is_looked_for_under_every_declared_environment(tmp_path):
    """The order check must run under each `--env` configuration, not only the
    default one.

    This is a regression guard for a false negative this harness actually had.
    Its first version ran the checker once, in the ambient environment, and
    reported `ORDER_DEPENDENT: passed` against vault-backlinks-mcp `95aefdb` --
    a tree where the dependence provably exists. Measured on that tree: the
    dependence appears under `VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0` and never
    in the default environment (0 of 15 pytest-randomly seeds by default, 23 of
    40 under the hostile setting). A detector run in the wrong configuration is
    not a detector.

    The fixture's checker is silent by default and fires only when the variable
    is set, so a harness that skips the non-default configurations cannot pass.
    """
    files = dict(CLEAN_FILES)
    files["scripts/order_independence_check.py"] = (
        "import os, sys\n"
        "if os.environ.get('SELFTEST_HARNESS_SWITCH') == '0':\n"
        "    print('ORDER-DEPENDENT: only visible under this configuration')\n"
        "    sys.exit(1)\n"
        "sys.exit(0)\n")
    repo = _repo(tmp_path, extra=files)

    quiet = run_harness(repo, "--guard-source", "src/guards.py",
                        "--guard-registry", "tests/test_witness.py",
                        "--env", "SELFTEST_HARNESS_UNRELATED=1")
    assert "ORDER_DEPENDENT" not in codes(quiet), (
        "the fixture checker fired in a configuration where it should be silent"
    )

    found = run_harness(repo, "--guard-source", "src/guards.py",
                        "--guard-registry", "tests/test_witness.py",
                        "--env", "SELFTEST_HARNESS_SWITCH=0")
    assert "ORDER_DEPENDENT" in codes(found), (
        "the order check was not run under the declared --env configuration, so "
        "an order dependence invisible in the default environment goes "
        "unreported -- the exact false negative this test exists to prevent"
    )


# --- the load-bearing rule ------------------------------------------------

def test_a_check_that_cannot_run_is_reported_not_dropped(tmp_path):
    """The rule the first adversarial review broke: it returned `refuted: []`
    while nine of ten verifiers had died, and the shape read as clean. A check
    that did not run must never be indistinguishable from one that passed."""
    repo = _repo(tmp_path, extra={k: v for k, v in CLEAN_FILES.items()
                                  if "order_independence" not in k})
    result = run_harness(repo, "--guard-source", "src/guards.py",
                         "--guard-registry", "tests/test_witness.py")
    assert result["status"] == "review_required", (
        "a repository with two checks unable to run reported complete"
    )
    assert "CHECK_DID_NOT_RUN" in codes(result)
    assert {"ORDER_DEPENDENT", "ENV_SENSITIVE"} <= skipped(result), (
        f"skipped checks were not named: {skipped(result)}"
    )
    assert "ORDER_DEPENDENT" not in result["checks_run"]


def test_a_broken_checker_is_a_skip_not_a_pass(tmp_path):
    """Exit code 2 from the delegate means it failed to answer. Reading that as
    'no order dependence' is how a collapsed check becomes a clean result."""
    files = dict(CLEAN_FILES)
    files["scripts/order_independence_check.py"] = (
        "import sys\nsys.stderr.write('exploded\\n')\nsys.exit(2)\n")
    repo = _repo(tmp_path, extra=files)
    result = run_harness(repo, *CLEAN_ARGS)
    assert "ORDER_DEPENDENT" in skipped(result)
    assert "ORDER_DEPENDENT" not in result["checks_run"]


# --- the meta-guard, same shape as the witness registry's -----------------

def test_every_code_the_tool_can_emit_is_demonstrated_here():
    """A code with no case in this dataset is a code nobody has seen fire.
    CHECK_DID_NOT_RUN is demonstrated by the two skip tests above."""
    source = Path(__file__).read_text(encoding="utf-8")
    undemonstrated = sorted(
        code for code in REQUIRED_ACTIONS
        if f'"{code}"' not in source and f"'{code}'" not in source
    )
    assert not undemonstrated, (
        f"code(s) the tool can emit with no case in the separation dataset: "
        f"{undemonstrated}. Add a world where each one fires, or remove it."
    )


def test_every_code_has_a_required_action():
    """`review_required` with no instruction is a warning, not a contract."""
    empty = sorted(code for code, action in REQUIRED_ACTIONS.items()
                   if not action or len(action) < 40)
    assert not empty, f"codes with a missing or stub required_action: {empty}"
