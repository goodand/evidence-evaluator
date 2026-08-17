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


def test_a_clean_repository_comes_back_complete(tmp_path):
    """Without this, a harness that fired on everything would satisfy every
    other test in this file."""
    repo = _repo(tmp_path, extra=CLEAN_FILES)
    result = run_harness(repo, *CLEAN_ARGS)
    assert result["status"] == "complete", (
        f"a clean repository produced review codes {codes(result)}: "
        f"{result['review_checks']}"
    )
    assert not result["checks_skipped"], (
        f"nothing should have been skipped here: {result['checks_skipped']}"
    )


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
