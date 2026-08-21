#!/usr/bin/env python3
"""Self-test harness: mechanical checks on whether a test suite proves anything.

Contract and agent rule: selftest-harness/AGENT_TOOL.md
Separation dataset (each code shown firing, clean case shown quiet):
selftest-harness/test_separation.py

WHY THIS EXISTS
---------------
This project's recurring defect is the vacuous guard: a check is added, and
whether it can actually fire is never established. Eighteen instances are on
record. The prose cautions against it were written by the same sessions that
then committed new instances, including cautions violated in the paragraph
below the one that stated them. Prose is not the mechanism.

The canonical harness in `.vault-harness/vault-md-retrieval/` already solved the
shape of this problem: a tool that returns `status` plus `review_checks[]`, each
with a `code` and a `required_action` the caller must execute, and a Validation
section demonstrating that each exception class actually fires while the normal
path stays quiet. That is a positive and a negative witness per code. This tool
reuses that contract rather than inventing another one.

THE LOAD-BEARING RULE
---------------------
    A check that did not run is not a check that passed.

The first adversarial review this harness is descended from returned
`{"confirmed": [...1 item...], "refuted": []}` while nine of its ten verifiers
had died on a spend limit. `refuted: []` was read as "nothing was refuted" when
it meant "no refutation finished". The aggregate shape made a collapse look like
a clean result. So every check here reports one of three states, never two, and
`CHECK_DID_NOT_RUN` is itself a review code that blocks `complete`.
"""
from __future__ import annotations

import argparse
import json
import os
import ast
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

CONTRACT_VERSION = "selftest-harness-v1"

# Codes are the tool's vocabulary. `test_separation.py` asserts that every code
# named here is demonstrated firing by some case in its dataset, so a code
# cannot be added as decoration.
REQUIRED_ACTIONS = {
    "CHECK_DID_NOT_RUN":
        "A check errored instead of reaching a verdict. Read its `detail`, fix "
        "the cause, and re-run. Do NOT treat the surrounding result as clean -- "
        "an unrun check carries no information either way.",
    "ORDER_DEPENDENT":
        "A test's outcome changes depending on what ran before it, so it is "
        "reporting the suite's history rather than the code. Find the leaking "
        "global (importlib.reload and module-level env reads are the usual "
        "causes; monkeypatch cannot undo a reload) and make the test build the "
        "world it needs.",
    "ORDER_DEPENDENT_ITEMWISE":
        "A test's outcome changes when tests are shuffled WITHIN their file, "
        "which the file-level checker cannot see. Read `outcomes_by_order` to "
        "find which ordering exposes it, reproduce with that exact "
        "--randomly-seed, and make the affected test build its own state "
        "instead of inheriting a sibling's.",
    "ENV_SENSITIVE":
        "The suite's outcome changes with an environment variable the package "
        "reads at import time. Either the tests depend on ambient "
        "configuration, or a guard is only reachable under one setting. Pin the "
        "configuration inside the tests that need it.",
    "WORKTREE_DIRTY":
        "The target repository has uncommitted changes or stray files. If a "
        "poison test or a verification agent left them, the numbers reported "
        "alongside this are measurements of an unknown tree. Inspect and revert "
        "before trusting anything else in this result.",
    "GUARD_WITHOUT_WITNESS":
        "A guard code appears in the source but no witness registry mentions "
        "it. Add a positive AND a negative witness. A guard nobody can show "
        "firing is indistinguishable from one that cannot.",
    "SUITE_NOT_GREEN":
        "The baseline suite does not pass, so every comparison below is against "
        "a broken baseline. Fix the baseline first.",
}


@dataclass
class Check:
    code: str
    state: str  # "passed" | "fired" | "did_not_run"
    detail: str = ""
    evidence: dict = field(default_factory=dict)


def _pytest(repo: Path, targets: list[str], env: dict[str, str] | None = None,
            python: str | None = None) -> tuple[dict[str, str], str]:
    """Run pytest and map node id -> outcome. --color=no is load-bearing:
    with colour on, outcomes are wrapped in ANSI escapes and the regex below
    matches nothing, which would report success for the wrong reason."""
    environ = dict(os.environ)
    if env:
        for key, value in env.items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
    proc = subprocess.run(
        [python or sys.executable, "-m", "pytest", *targets, "-v", "--tb=no",
         "--color=no", "-p", "no:cacheprovider"],
        cwd=repo, capture_output=True, text=True, env=environ,
    )
    pattern = re.compile(
        r"^(?P<node>\S+::\S+?)\s+(?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)")
    outcomes: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        match = pattern.match(line.strip())
        if match:
            outcomes[match.group("node")] = match.group("outcome")
    return outcomes, proc.stdout[-4000:]


def check_suite_green(repo: Path) -> Check:
    try:
        outcomes, tail = _pytest(repo, ["tests/"])
    except Exception as exc:  # noqa: BLE001
        return Check("SUITE_NOT_GREEN", "did_not_run", f"pytest could not run: {exc!r}")
    if not outcomes:
        return Check("SUITE_NOT_GREEN", "did_not_run",
                     "no test outcomes could be parsed", {"tail": tail})
    bad = {n: o for n, o in outcomes.items() if o in ("FAILED", "ERROR")}
    if bad:
        return Check("SUITE_NOT_GREEN", "fired",
                     f"{len(bad)} of {len(outcomes)} tests are failing",
                     {"failing": sorted(bad)[:20], "total": len(outcomes)})
    return Check("SUITE_NOT_GREEN", "passed",
                 f"{len(outcomes)} tests, none failing", {"total": len(outcomes)})


def check_order_independence(repo: Path, env_matrix: list[dict]) -> Check:
    """Delegates to the target repo's own checker when it has one, rather than
    keeping a second implementation of the same comparison in this file. The
    project rule is one canonical copy; a harness that re-implements what it
    audits becomes the thing that drifts.

    Runs the checker under the DEFAULT configuration and under every `--env`
    configuration, because an order dependence can be entirely invisible in
    one and obvious in another. This is not defensive speculation -- the first
    version of this function ran the checker once, in the default environment,
    and returned `ORDER_DEPENDENT: passed` on a tree where the dependence
    demonstrably existed (vault-backlinks-mcp `95aefdb`, the F2 defect). It was
    a false negative in this harness.

    Measured on that tree: the order dependence surfaced under
    `VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0` and never in the default
    environment -- 0 of 15 pytest-randomly seeds found it by default, 23 of 40
    found it under the hostile setting. The environment is not a detail the
    detector can be run without.

    See docs/PRIOR_ART_ORDER_DEPENDENCE_20260818.md.
    """
    script = repo / "scripts" / "order_independence_check.py"
    if not script.exists():
        return Check("ORDER_DEPENDENT", "did_not_run",
                     f"no order-independence checker at {script.relative_to(repo)}; "
                     "this class of defect was NOT examined")
    # `None` is the default configuration, and it goes first so its report is
    # the one a reader sees when several configurations fire.
    configs: list[dict | None] = [None, *env_matrix]
    fired = []
    for config in configs:
        environ = dict(os.environ)
        for key, value in (config or {}).items():
            if value is None:
                environ.pop(key, None)
            else:
                environ[key] = value
        proc = subprocess.run([sys.executable, str(script)], cwd=repo,
                              capture_output=True, text=True, env=environ)
        if proc.returncode == 1:
            fired.append({"env": config or "default",
                          "report": proc.stdout[-1500:]})
        elif proc.returncode != 0:
            return Check("ORDER_DEPENDENT", "did_not_run",
                         f"checker exited {proc.returncode} under "
                         f"{config or 'default'}",
                         {"stderr": proc.stderr[-1000:]})
    if fired:
        return Check("ORDER_DEPENDENT", "fired",
                     f"outcomes changed with test order under "
                     f"{len(fired)} of {len(configs)} configuration(s)",
                     {"configurations": fired})
    return Check("ORDER_DEPENDENT", "passed",
                 f"no cross-file order dependence under {len(configs)} "
                 f"configuration(s)",
                 {"note": "same-file leakage is not covered; see the script. "
                          "Only the configurations passed via --env were tried."})


def check_env_sensitivity(repo: Path, env_matrix: list[dict]) -> Check:
    """Run the suite under each declared configuration and diff the outcomes.

    This is the F2 class. A witness that passes with the fallback on and fails
    with it off is reporting its environment, not its guard -- and the failure
    is invisible to anyone who only ever runs the default configuration.
    """
    if not env_matrix:
        return Check("ENV_SENSITIVE", "did_not_run",
                     "no --env configurations given; import-time configuration "
                     "was NOT examined")
    baseline, _ = _pytest(repo, ["tests/"])
    if not baseline:
        return Check("ENV_SENSITIVE", "did_not_run", "baseline outcomes unparseable")
    differences = []
    for env in env_matrix:
        outcomes, _ = _pytest(repo, ["tests/"], env=env)
        if not outcomes:
            return Check("ENV_SENSITIVE", "did_not_run",
                         f"outcomes unparseable under {env}")
        for node, outcome in outcomes.items():
            if baseline.get(node) not in (None, outcome):
                differences.append(
                    {"test": node, "env": env,
                     "default": baseline.get(node), "under_env": outcome})
    if differences:
        return Check("ENV_SENSITIVE", "fired",
                     f"{len(differences)} outcome(s) changed with the environment",
                     {"differences": differences[:20]})
    return Check("ENV_SENSITIVE", "passed",
                 f"stable across {len(env_matrix)} configuration(s)")


PINNED_SEEDS = (2, 3, 4, 5, 8)
"""Fixed orderings, not a lottery.

`pytest-randomly` picks a fresh seed per run by default, which makes it a
discovery tool and a poor regression gate. Measured on this project's two known
order dependences: each was surfaced by roughly 6 in 10 seeds, so a single
random-seed run misses ~40% of the time -- worse than the deterministic
file-level checker it would replace.

These five are the intersection of the seeds that surfaced BOTH known defects,
and a given seed reproduces (seed 2 checked 3 times, 3 hits). Pinning them makes
the gate deterministic while keeping five distinct orderings.

  cross-file (vault-backlinks-mcp 95aefdb, hostile env): 23/40 seeds
  same-file (green-by-default two-test fixture):         25/40 seeds

These seeds are known to catch THESE defects. They are not a guarantee for
future ones -- when a random-seed run finds something these five miss, add its
seed here rather than replacing them.
"""


def check_order_independence_itemwise(repo: Path, env_matrix: list[dict],
                                      python: str) -> Check:
    """Shuffle tests WITHIN files, which the file-level checker cannot do.

    The delegated `scripts/order_independence_check.py` compares whole-suite
    against file-alone, so two tests leaking into each other inside one file
    stay together in both runs and are invisible to it. Measured: on a
    green-by-default same-file fixture that checker reports OK, while
    `pytest-randomly` surfaced it on 25 of 40 seeds.

    A test whose outcome differs between any two orderings is order-dependent;
    no "correct" baseline is needed, only disagreement.
    """
    # A probe that cannot even be launched (missing interpreter, not
    # executable) must degrade to did_not_run like any other unavailable
    # check. Letting OSError escape here crashed the whole tool and produced
    # no JSON at all -- found by `test_itemwise_reports_a_missing_plugin_as_a_skip`.
    try:
        probe = subprocess.run([python, "-c", "import pytest_randomly"],
                               capture_output=True, text=True)
    except OSError as exc:
        return Check("ORDER_DEPENDENT_ITEMWISE", "did_not_run",
                     f"could not run {python}: {exc!r}; within-file ordering "
                     "was NOT examined")
    if probe.returncode != 0:
        return Check("ORDER_DEPENDENT_ITEMWISE", "did_not_run",
                     f"pytest-randomly is not importable by {python}; "
                     "within-file ordering was NOT examined. Install it, or pass "
                     "--python pointing at an interpreter that has it.")
    disagreements = []
    for config in [None, *env_matrix]:
        seen: dict[str, dict[str, str]] = {}
        # Definition order first, then each pinned shuffle.
        orders: list[list[str]] = [["-p", "no:randomly"]]
        orders += [[f"--randomly-seed={seed}"] for seed in PINNED_SEEDS]
        for extra in orders:
            outcomes, _ = _pytest(repo, ["tests/", *extra], env=config,
                                  python=python)
            if not outcomes:
                return Check("ORDER_DEPENDENT_ITEMWISE", "did_not_run",
                             f"outcomes unparseable for {extra} under "
                             f"{config or 'default'}")
            label = " ".join(extra)
            for node, outcome in outcomes.items():
                previous = seen.setdefault(node, {})
                previous[label] = outcome
        for node, by_order in seen.items():
            if len(set(by_order.values())) > 1:
                disagreements.append({"test": node,
                                      "env": config or "default",
                                      "outcomes_by_order": by_order})
    if disagreements:
        return Check("ORDER_DEPENDENT_ITEMWISE", "fired",
                     f"{len(disagreements)} test(s) changed outcome across "
                     f"pinned orderings",
                     {"seeds": list(PINNED_SEEDS),
                      "disagreements": disagreements[:10]})
    return Check("ORDER_DEPENDENT_ITEMWISE", "passed",
                 f"stable across definition order plus {len(PINNED_SEEDS)} "
                 f"pinned shuffles",
                 {"seeds": list(PINNED_SEEDS),
                  "note": "these seeds caught this project's two known "
                          "dependences; they are not a proof for unknown ones"})


def check_worktree_clean(repo: Path) -> Check:
    proc = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return Check("WORKTREE_DIRTY", "did_not_run",
                     f"git status failed: {proc.stderr.strip()[:200]}")
    entries = [line for line in proc.stdout.splitlines() if line.strip()]
    if entries:
        return Check("WORKTREE_DIRTY", "fired",
                     f"{len(entries)} uncommitted path(s)", {"paths": entries[:20]})
    return Check("WORKTREE_DIRTY", "passed", "tree clean")


def check_guard_witnesses(repo: Path, source: str | None,
                          registry: str | None) -> Check:
    """Compare guard codes in the source against codes named in the registry.

    Parsed, not matched. Following this workspace's canonical scanner
    (`concept-gate-taxonomy/test_guard_negative_coverage.py`, documented in
    `concept-gate-codex-mcp-wt/docs/HARNESS_KNOWHOW.md` §B4a), which uses AST
    for two reasons that both apply here: it does not import the file it
    audits, and it has no character class that someone has to remember to
    widen.

    The regex this replaces was `r'"code":\\s*"([A-Z0-9_]+)"'`, whose class was
    itself a hand-fixed bug -- the original `[A-Z_]+` skipped every code
    containing a digit. Measured 2026-08-22: both forms return the same 11
    codes on the real target, but on a probe where a code appears in a
    docstring and in a comment the regex returned three and the parse returned
    one. The regex counted prose as guards, so a witness naming a code that
    only ever appeared in a comment would have satisfied the check.
    """
    if not source or not registry:
        return Check("GUARD_WITHOUT_WITNESS", "did_not_run",
                     "--guard-source and --guard-registry not both given; "
                     "witness completeness was NOT examined")
    source_path, registry_path = repo / source, repo / registry
    for path in (source_path, registry_path):
        if not path.exists():
            return Check("GUARD_WITHOUT_WITNESS", "did_not_run",
                         f"{path} does not exist")
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        return Check("GUARD_WITHOUT_WITNESS", "did_not_run",
                     f"{source} could not be parsed: {exc}; witness "
                     "completeness was NOT examined")
    in_source: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if (isinstance(key, ast.Constant) and key.value == "code"
                    and isinstance(value, ast.Constant)
                    and isinstance(value.value, str)):
                in_source.add(value.value)
    registry_text = registry_path.read_text(encoding="utf-8")
    missing = sorted(code for code in in_source
                     if not re.search(rf'\b{re.escape(code)}\b', registry_text))
    if not in_source:
        return Check("GUARD_WITHOUT_WITNESS", "did_not_run",
                     f"no guard codes found in {source}; the pattern may not "
                     "match how this project spells them")
    if missing:
        return Check("GUARD_WITHOUT_WITNESS", "fired",
                     f"{len(missing)} guard code(s) have no witness",
                     {"missing": missing, "codes_in_source": len(in_source)})
    return Check("GUARD_WITHOUT_WITNESS", "passed",
                 f"all {len(in_source)} guard code(s) named in the registry")


def evaluate(repo: Path, env_matrix: list[dict], guard_source: str | None,
             guard_registry: str | None, python: str | None = None) -> dict:
    checks = [
        check_worktree_clean(repo),
        check_suite_green(repo),
        check_order_independence(repo, env_matrix),
        check_order_independence_itemwise(repo, env_matrix,
                                          python or sys.executable),
        check_env_sensitivity(repo, env_matrix),
        check_guard_witnesses(repo, guard_source, guard_registry),
    ]
    review = []
    for check in checks:
        if check.state == "fired":
            review.append({"code": check.code, "detail": check.detail,
                           "evidence": check.evidence,
                           "required_action": REQUIRED_ACTIONS[check.code]})
        elif check.state == "did_not_run":
            review.append({"code": "CHECK_DID_NOT_RUN",
                           "skipped_check": check.code, "detail": check.detail,
                           "required_action": REQUIRED_ACTIONS["CHECK_DID_NOT_RUN"]})
    return {
        "contract_version": CONTRACT_VERSION,
        "repo": str(repo),
        "status": "complete" if not review else "review_required",
        "checks_run": [c.code for c in checks if c.state != "did_not_run"],
        "checks_skipped": [c.code for c in checks if c.state == "did_not_run"],
        "review_checks": review,
        "detail": {c.code: {"state": c.state, "detail": c.detail} for c in checks},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repo", help="path to the repository to audit")
    parser.add_argument("--env", action="append", default=[], metavar="K=V",
                        help="environment configuration to also run the suite "
                             "under; repeatable. Use K= to unset K.")
    parser.add_argument("--guard-source", default=None,
                        help='repo-relative file whose \'"code": "X"\' literals '
                             "are the guards")
    parser.add_argument("--guard-registry", default=None,
                        help="repo-relative file expected to name every guard code")
    parser.add_argument("--python", default=None,
                        help="interpreter used to run the target's suite. Point "
                             "this at a virtualenv that has pytest-randomly, or "
                             "the within-file ordering check reports "
                             "CHECK_DID_NOT_RUN. Defaults to this interpreter.")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    if not repo.is_dir():
        print(f"not a directory: {repo}", file=sys.stderr)
        return 2

    env_matrix = []
    for item in args.env:
        key, _, value = item.partition("=")
        env_matrix.append({key: (value if value else None)})

    result = evaluate(repo, env_matrix, args.guard_source, args.guard_registry,
                      args.python)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
