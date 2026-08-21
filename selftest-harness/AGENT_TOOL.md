# Self-Test Harness — Agent Tool Contract

Deliberately shaped after `.vault-harness/vault-md-retrieval/AGENT_TOOL.md`.
That harness already solved this problem: a tool returning `status` plus
`review_checks[]`, each with a `code` and a `required_action` the caller must
execute, and a Validation section demonstrating that each exception class
actually fires while the normal path stays quiet. This one reuses that contract
rather than inventing a second one.

## Command

```
python3 selftest-harness/selftest_agent_tool.py <repo> \
    [--env KEY=VALUE]... [--guard-source PATH] [--guard-registry PATH]
```

`--env KEY=VALUE` adds a configuration to also run the suite under; repeatable.
`KEY=` unsets. `--guard-source` is the file whose `"code": "X"` literals are the
guards; `--guard-registry` is the file expected to name every one of them.
Omitted options do not silently pass — the corresponding check reports
`CHECK_DID_NOT_RUN`.

`--python` names the interpreter used for the within-file ordering check, which
needs `pytest-randomly`. Omitting it is safe: the tool falls back to the durable
venv at `~/.claude/venvs/itemwise/bin/python` when present, then to its own
interpreter, and an interpreter without the plugin degrades to
`CHECK_DID_NOT_RUN`, never to a quiet pass. Recreate the venv with
`python3 -m venv ~/.claude/venvs/itemwise && ~/.claude/venvs/itemwise/bin/pip
install pytest pytest-randomly`. (The first version pinned a session job path,
which is deleted with the session — that is why the durable location exists.)

Exit 0 on `complete`, 1 on `review_required`, 2 on bad invocation.

## Agent Rule

1. Run this before asserting that a suite guards anything.
2. If `status=complete`, the five checks ran and none fired. That is not
   "the code is correct" — it is "these five mechanical failure modes are
   absent."
3. If `status=review_required`, execute every `review_checks[].required_action`
   before reporting. Do not summarize the result as clean because the count is
   small.
4. **Never read a skipped check as a passed check.** `checks_skipped` is not a
   shorter `checks_run`. Every skip appears as a `CHECK_DID_NOT_RUN` review
   entry naming the check in `skipped_check`.
5. Report `checks_run` alongside any conclusion. A verdict without its scope
   invites the reader to assume the scope was everything.
6. Numbers here are per-invocation on one machine. When quoting one, quote the
   configuration it was measured under — `--env` changes outcomes, which is the
   entire point of the `ENV_SENSITIVE` check.

## Exception Checks

- `SUITE_NOT_GREEN`: the baseline suite has failures, so every comparison is
  against a broken baseline
- `WORKTREE_DIRTY`: uncommitted changes or stray files, so the measurements
  describe an unknown tree
- `ORDER_DEPENDENT`: a test's outcome changes with what ran before it
- `ENV_SENSITIVE`: the suite's outcome changes with an environment variable read
  at import time
- `GUARD_WITHOUT_WITNESS`: a guard code in the source that no witness registry
  names
- `CHECK_DID_NOT_RUN`: a check errored or lacked its inputs. Blocks `complete`
  by design

## The Load-Bearing Rule

> A check that did not run is not a check that passed.

This is not a stylistic preference. The adversarial review this harness descends
from returned `{"confirmed": [1 item], "refuted": []}` while nine of its ten
verifiers had died on a spend limit. `refuted: []` meant "no refutation
finished" and was read as "nothing was refuted". The aggregate shape made a
collapse look like a clean result, and one of those dead verifiers had left
`review_required = False  # BROKEN` in production code on its way out.

So a check reports one of three states, never two, and the third one blocks.

## Validation

`selftest-harness/test_separation.py` — 12 cases.

A clean fixture repository returns `complete` with nothing skipped. Each of
`SUITE_NOT_GREEN`, `WORKTREE_DIRTY`, `GUARD_WITHOUT_WITNESS`, `ENV_SENSITIVE`,
`ORDER_DEPENDENT`, and `CHECK_DID_NOT_RUN` fires on a world built to trigger it.
So the normal path stays quiet while every named class can be shown speaking.

A meta-guard reads this tool's own `REQUIRED_ACTIONS` and fails on any code with
no case in the dataset, so a code cannot be added as decoration.

Poison-tested four ways:

| mutation | result |
|---|---|
| skipped checks no longer block `complete` | both skip cases FAILED |
| a decorative code with no fixture added | meta-guard FAILED |
| `[A-Z0-9_]+` narrowed to `[A-Z_]+` | digit-code case FAILED (upstream: vault-backlinks-mcp `95aefdb`) |
| order check run in the default configuration only | cross-configuration case FAILED |

The fourth was not hypothetical. It reproduces a false negative this harness
shipped with, and it was confirmed end-to-end against the defect-bearing
revision: before the fix the harness reported `ORDER_DEPENDENT: passed` on
`95aefdb`; after it, `outcomes changed with test order under 1 of 2
configuration(s)`, naming
`test_guard_fires_on_its_positive_witness[FILESYSTEM_FALLBACK_USED]`.

Proving a detector on the revision where the defect still lives is deliberate.
The fix for that defect normalized the module state that produced the
asymmetry, so on the current tree no detector can reproduce it — the repair
destroyed the evidence that the detector works.

## What It Does Not Establish

- **Five failure modes, not correctness.** `complete` says nothing about whether
  the assertions are meaningful, only that these five mechanical defects are
  absent.
- **`ENV_SENSITIVE` sees only the configurations you pass.** With no `--env` it
  reports `CHECK_DID_NOT_RUN`, not "insensitive".
- **`ORDER_DEPENDENT` is delegated** to the target repo's own
  `scripts/order_independence_check.py`, so the harness inherits that tool's
  limits: **cross-file only** — two tests leaking into each other inside one
  file stay together in both runs and are invisible.
  It runs under the default configuration *and* every `--env` configuration,
  which is not optional. The first version of this check ran once, in the
  ambient environment, and reported `passed` against `vault-backlinks-mcp`
  `95aefdb` where the dependence provably exists — a false negative in this
  harness, found while verifying an external prior-art report.
  Measured on that tree: the dependence appears under
  `VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0` and never in the default
  environment. So a configuration you do not pass is a configuration nobody
  checked.
- **`pytest-randomly` is item-level and this checker is not.** Measured on the
  same tree, `pytest-randomly 4.1.0` (Python 3.13.13, pytest 9.1.1) surfaced
  the same defect on **23 of 40 seeds** under the hostile environment and **0 of
  15** by default. A single random-seed run therefore misses it ~43% of the
  time, which is why adopting it as a regression gate requires **pinned seeds**,
  not its default behaviour. Until that is wired in, this checker's advantage is
  determinism, not coverage.
  `detect-test-pollution 1.2.0` installs and runs on this stack but **cannot
  address this defect class**: it requires the failing test to pass in
  isolation, and the F2 witness does the opposite (fails alone, passes in the
  suite) — a *brittle* test, not a *victim*.
  Details and measurements: `docs/PRIOR_ART_ORDER_DEPENDENCE_20260818.md`.
- **`GUARD_WITHOUT_WITNESS` matches a spelling.** It finds `"code": "X"`
  literals. A project that names guards differently gets
  `CHECK_DID_NOT_RUN`, which is the honest answer, not silence.
- **Mentioning a code is not witnessing it.** This check confirms the registry
  *names* every guard. Whether each has a working positive and negative witness
  is the registry's own job — see `vault-backlinks-mcp/tests/test_guard_witness.py`.

## First Run

Against `vault-backlinks-mcp` at 89 passed with a clean tree, the harness
returned `review_required`: two tests in `test_contracts.py` change from PASSED
to FAILED under `VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0`. That defect was known
and unfixed; nobody had to remember to look for it.
