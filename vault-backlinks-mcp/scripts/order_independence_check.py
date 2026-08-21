#!/usr/bin/env python3
"""Fail if any test's outcome depends on what ran before it.

WHY THIS EXISTS
---------------
Adversarial review finding F2 (2026-08-17) was invisible to the test suite for
a reason that had nothing to do with the assertion being weak: the
FILESYSTEM_FALLBACK_USED witness PASSED in the full suite and FAILED when run
alone. `test_contracts.py` calls `importlib.reload(contracts)` after
`monkeypatch.delenv(...)`, and monkeypatch cannot undo a reload -- so from that
point on, every later test saw a module reconfigured to "fallback enabled",
which masked the witness's dependence on the ambient environment.

Nobody would have found that by reading the tests. It was found by running the
file alone and noticing the result changed. That comparison is mechanical, so
it should not depend on somebody thinking to do it.

This is deliberately dependency-free -- no pytest-randomly, no
pytest-random-order. It compares two things this project can always run:

    outcome of every test in the full-suite run
    outcome of every test when its FILE runs by itself

Any test that disagrees between the two is order-dependent, which means its
result is reporting the suite's history rather than the code under test.

WHAT IT DOES NOT CATCH
----------------------
1. File-level isolation only. Two tests inside the SAME file can still leak
   into each other and this script will not see it, because they stay together
   in both runs. Catching that needs per-test isolation (slow) or genuine
   shuffling.

2. It only finds order dependence that MANIFESTS in the environment it is run
   in. This was measured, not assumed. Against the genuine pre-fix tree
   (commit 95aefdb), with the F2 defect present:

       VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0 ./order_independence_check.py
           -> ORDER-DEPENDENT: FILESYSTEM_FALLBACK_USED
              in full suite PASSED, run alone FAILED

       ./order_independence_check.py          (default environment)
           -> OK, nothing found

   In the default environment the module global happened to be bound either
   way, so there was no asymmetry to see. Running this once, in one
   environment, is therefore NOT evidence that the suite is order-independent.
   Run it under the configurations the package actually reads --
   for this package, at minimum with the filesystem fallback both on and off.

A clean report means "no cross-FILE order dependence that shows up in THIS
environment", which is narrower than it looks. Do not quote it as more.

Exit codes: 0 clean, 1 order-dependent tests found, 2 could not run.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"

OUTCOME = re.compile(r"^(?P<node>\S+::\S+?)\s+(?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)")


def run(targets: list[str]) -> dict[str, str]:
    """Map test node id -> outcome for one pytest invocation."""
    proc = subprocess.run(
        # --color=no matters: with colour on, every outcome word is wrapped in
        # ANSI escapes and the regex below silently matches nothing, which
        # would make this script report "clean" for the wrong reason.
        [sys.executable, "-m", "pytest", *targets, "-v", "--tb=no",
         "--color=no", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True,
    )
    outcomes: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        match = OUTCOME.match(line.strip())
        if match:
            outcomes[match.group("node")] = match.group("outcome")
    if not outcomes:
        print(f"could not parse any outcome from: pytest {' '.join(targets)}",
              file=sys.stderr)
        print(proc.stdout[-2000:], file=sys.stderr)
        raise SystemExit(2)
    return outcomes


def main() -> int:
    files = sorted(p for p in TESTS.glob("test_*.py"))
    if not files:
        print(f"no test files under {TESTS}", file=sys.stderr)
        return 2

    together = run(["tests/"])
    print(f"full suite: {len(together)} tests")

    disagreements: list[tuple[str, str, str]] = []
    for path in files:
        rel = f"tests/{path.name}"
        alone = run([rel])
        print(f"  {rel}: {len(alone)} tests alone")
        for node, outcome_alone in alone.items():
            outcome_together = together.get(node)
            if outcome_together is None:
                disagreements.append((node, "NOT COLLECTED in full suite", outcome_alone))
            elif outcome_together != outcome_alone:
                disagreements.append((node, outcome_together, outcome_alone))

    if not disagreements:
        print(f"\nOK -- no cross-file order dependence across {len(files)} files.")
        print("(Same-file leakage is NOT checked; see this script's docstring.)")
        return 0

    print(f"\nORDER-DEPENDENT: {len(disagreements)} test(s) changed outcome.")
    print("Each of these reports the suite's history, not the code under test.\n")
    for node, in_suite, when_alone in disagreements:
        print(f"  {node}\n      in full suite: {in_suite}\n      run alone:     {when_alone}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
