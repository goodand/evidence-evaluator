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

`selftest-harness/test_separation.py` — 11 cases.

A clean fixture repository returns `complete` with nothing skipped. Each of
`SUITE_NOT_GREEN`, `WORKTREE_DIRTY`, `GUARD_WITHOUT_WITNESS`, `ENV_SENSITIVE`,
`ORDER_DEPENDENT`, and `CHECK_DID_NOT_RUN` fires on a world built to trigger it.
So the normal path stays quiet while every named class can be shown speaking.

A meta-guard reads this tool's own `REQUIRED_ACTIONS` and fails on any code with
no case in the dataset, so a code cannot be added as decoration.

Poison-tested three ways (2026-08-17):

| mutation | result |
|---|---|
| skipped checks no longer block `complete` | both skip cases FAILED |
| a decorative code with no fixture added | meta-guard FAILED |
| `[A-Z0-9_]+` narrowed to `[A-Z_]+` | digit-code case FAILED (upstream: vault-backlinks-mcp `95aefdb`) |

## What It Does Not Establish

- **Five failure modes, not correctness.** `complete` says nothing about whether
  the assertions are meaningful, only that these five mechanical defects are
  absent.
- **`ENV_SENSITIVE` sees only the configurations you pass.** With no `--env` it
  reports `CHECK_DID_NOT_RUN`, not "insensitive".
- **`ORDER_DEPENDENT` is delegated** to the target repo's own
  `scripts/order_independence_check.py`, so the harness inherits that tool's
  limits: cross-file only (same-file leakage is invisible), and only dependence
  that manifests in the environment it runs in. Measured: against the pre-fix
  tree it named the F2 defect under `VAULT_BACKLINKS_FILESYSTEM_FALLBACK=0` and
  found nothing in the default environment.
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
