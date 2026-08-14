# evidence-evaluator

Does a zero-context agent find and correctly cite the right sources — in
*your* corpus, driven by *your* choice of CLI agent (Claude CLI, Codex CLI,
or your own adapter)?

## Where this came from

Extracted 2026-08-08 from
`concept-gate-codex-mcp-wt/experiments/2026-08-07_handoff_dynamic_controller`
in the `concept-gate-taxonomy` workspace, where it tested whether a
zero-context coding agent could find the files it needed to resume work from
that one repository's `docs/HANDOFF.md`. Two things made that source code a
good extraction candidate rather than a rewrite target:

- **Zero hardcoded workspace paths** in the four core engine files
  (`evaluator.py`, `providers.py`, `runner.py`, `contract.py`) — verified by
  grep before extraction, not assumed.
- **A provider layer that already worked across two different agent CLIs**
  (`providers.py`'s `resolve_provider()` dispatches to a Claude CLI adapter
  or a Codex CLI adapter by config, both under process-level sandboxing) —
  this is the part that makes "does it work with Codex too" a fact about the
  code, not an aspiration.

## What moved and what stayed

| | Moved here | Stayed in the source workspace |
|---|---|---|
| Engine | `contract.py`, `evaluator.py`, `runner.py`, `providers.py`, `subject_tool.py`, `mcp_bridge.py` | — |
| Schema | The case/gold/trace JSON contract (generic evidence-gathering vocabulary) | — |
| Data | — | `public_cases/cases.json`, `hidden_gold/gold.json`, the actual corpus, `docs/HANDOFF.md` |
| Protocol machinery | Portable staged factorial runner and freeze receipt | Source-specific primary authorization and safety-audit governance |

The portable factorial runner added here is narrower than the source
experiment: it compares handoff search workflow and retrieval-helper use.
Source-specific primary authorization and safety-audit governance remain
outside this package.

## Obsidian vault retrieval

`evidence_evaluator.retrieval` is the reusable, read-only retrieval layer for
an Obsidian Markdown vault. It is deliberately separate from the evaluator
engine above:

- It searches and reads only Markdown under a caller-owned `VaultProfile`.
- It combines exact terms, local BM25, Markdown/wiki-link graph edges, and
  optional Obsidian CLI links/backlinks using a recall-first policy.
- It canonicalizes symlink aliases before graph expansion, returns only
  canonical paths, and blocks private evaluation and VCS paths at one shared
  policy boundary.
- It never writes a vault, rebuilds an Obsidian index, reads a gold set, or
  decides that no evidence exists. A budget stop and zero hits remain
  `review_required`.

The design and migration evidence are recorded in
[`docs/DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md`](docs/DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md)
and
[`docs/MIGRATION_STATUS_OBSIDIAN_RETRIEVAL.md`](docs/MIGRATION_STATUS_OBSIDIAN_RETRIEVAL.md).

### CLI

Create a profile from
[`examples/vault-profile.example.json`](examples/vault-profile.example.json),
then run either the installed script or the module directly:

```bash
evidence-vault --profile /absolute/path/vault-profile.json search "handoff state"
evidence-vault --profile /absolute/path/vault-profile.json read docs/HANDOFF.md \
  --line-start 1 --line-count 120

# No install is required when running from a checkout.
python3 -m evidence_evaluator.retrieval.cli --root /absolute/path/to/vault \
  --vault-name "My Vault" search "handoff state"
```

The optional MCP transport is the same service, not a second search
implementation:

```bash
EVIDENCE_VAULT_PROFILE=/absolute/path/vault-profile.json evidence-vault-mcp
```

Install it with `pip install 'evidence-evaluator[obsidian-mcp]'` when the
`mcp` dependency is not already present. It exposes three read-only tools:

- `vault_search` — recall-first hybrid + graph search over the vault.
- `vault_read` — read a byte-range of one canonical Markdown path.
- `vault_backlinks` — which documents link to a given path. This is not a
  second graph implementation; it exposes the same backlink data the graph
  walk already computes internally, bounded and canonicalized the same way
  as `vault_search`.

`vault_search` returns the bounded `compact-v1` projection by default. Pass
`include_diagnostics=true` only for retrieval development; it restores the
full candidate pool and turn trace and can be very large. Set
`EVIDENCE_MCP_AUDIT_LOG` to record content-free JSONL metadata for each call,
and `EVIDENCE_MCP_MAX_CALLS` to enforce a per-process call budget.

Every response carries `fallback_used`: `null` when the Obsidian CLI answered
directly, or the name of the degraded source (currently `"filesystem"`) when
the CLI was unavailable and the filesystem link graph carried the answer
instead. A non-null `fallback_used` always accompanies `status: "partial"`
and `review_required: true` — the call still returns what it knows, it does
not fail silently. Callers must search, inspect `fallback_used` and the
returned warnings, then read or check backlinks on selected canonical files
before treating a result as settled.

### Codex global registration

Register the checkout launcher once. The explicit environment keeps the
globally visible server bound to the intended vault:

```bash
codex mcp add evidence-vault-mcp \
  --env EVIDENCE_VAULT_ROOT=/Users/jaehyuntak/Desktop/Project_in_progress \
  --env EVIDENCE_VAULT_NAME=Project_in_progress \
  -- /Users/jaehyuntak/Desktop/Project_in_progress/evidence-evaluator/scripts/run_obsidian_vault_mcp.sh
```

Verify the saved definition with `codex mcp get evidence-vault-mcp` and start
a new Codex session before testing the tools. A configuration change cannot
add tools to a session that is already running. Remove only this registration
with `codex mcp remove evidence-vault-mcp`.

Claude Code can use the same launcher from a project-scope `.mcp.json`. Both
clients must point to this main checkout, not a temporary `.claude/worktrees`
path.

### Zero-context handoff canary

The one-case canary starts a fresh ephemeral Codex subject with user config,
rules, native shell/file tools, and unrelated MCP servers disabled. The only
model-visible tools are `vault_search`, `vault_read`, and `vault_backlinks`.
Its supervisor log is then used to verify that every citation was covered by
an actual bounded read. Runtime, Retrieval, and Reconstruction remain separate
outcomes; the canary does not estimate workflow-arm effects or vault-wide
recall.

```bash
python3 -m evidence_evaluator.handoff_canary \
  --profile private_eval/handoff-mcp-canary-v1/profile.json \
  --case private_eval/handoff-mcp-canary-v1/case.json \
  --gold private_eval/handoff-mcp-canary-v1/gold.json \
  --model gpt-5.6-sol \
  --output results/handoff-mcp-canary-v1.json
```

The five arguments above are explicit by design. Private case/gold and run
artifacts are ignored by Git. See
[`docs/HANDOFF_MCP_CANARY.md`](docs/HANDOFF_MCP_CANARY.md) for the contract,
failure interpretation, and acceptance checks.

### Staged workflow/subagent factorial

`evidence-handoff-factorial` compares fixed recall-first search, dynamic
action choice, and a retrieval-only helper through the host-owned MCP action
runtime. The six-case canary remains transport qualification and is not reused
as arm evidence. See
[`docs/HANDOFF_FACTORIAL_V2.md`](docs/HANDOFF_FACTORIAL_V2.md) for the frozen
design, commands, and current unrun status.

### Obsidian CLI and permission lanes

The filesystem graph is always available. Obsidian CLI graph expansion is
additive: it runs each command with `cwd` set to the profile root and falls
back with an explicit warning when the local CLI cannot answer. This matters
for agent sandboxes: a host terminal can reach the Obsidian IPC endpoint while
a managed subprocess with the same command may not. Validate the intended
runtime, rather than assuming host success transfers to an MCP process:

```bash
cd /absolute/path/to/vault
obsidian backlinks vault="My Vault" path=docs/HANDOFF.md counts format=json
```

If that command fails in the MCP runtime, use the returned filesystem results
and warning, or grant that runtime only the local IPC capability required by
Obsidian. Do not disable the path policy or pass a symlink alias to make a
CLI error disappear.

## What was intentionally dropped or changed

- **The four fixed arms** (`S_STATIC`/`R_STATIC`/`S_DYNAMIC`/`R_DYNAMIC`) and
  their `ARM_HAS_SUBAGENT`/`ARM_IS_DYNAMIC` lookup table were a specific
  experimental design, not a schema requirement. `run_case()` here takes
  `has_subagent` and `is_dynamic` directly; `arm` is a free-form string tag
  for your own bookkeeping and is no longer validated against a fixed set.
- **`FROZEN_SURFACE_FILES` / `frozen_surface_hashes` / `frozen_surface_drift`**
  were dropped from `evaluator.py` — they hardcoded that one experiment's
  config filenames. The underlying pattern (hash your grader's own source so
  a patched-but-clean-looking copy can't silently run) is kept as
  `source_hashes()` / `run_clean_judge()`, generalized to just the two files
  this package ships.
- **A real bug in the source's CLI was fixed here**: `_evaluator.py --emit-pins`
  failed with "the following arguments are required: --payload" because
  `--payload` was `required=True` even on the path that never reads a
  payload. Fixed in `evaluator.py` by making `--payload` optional and
  checking it only where it's actually needed. (Worth reporting upstream;
  out of scope for this extraction to do that.)
- **`FORBIDDEN_RUNTIME_KEYS`, the closed `ACTIONS` set, and the `C1`-`C4`
  failure codes** are kept as the *default* vocabulary because they're
  already generic (search/read/cite, not anything workspace-specific) — but
  they're plain tuples/dicts in `contract.py`, not hardcoded into the
  validators' control flow beyond membership checks, so add or drop entries
  for your own setup freely.

## Layout and import modes

```
evidence_evaluator/
  contract.py      case/gold/trace/subagent-output schema + validators
  evaluator.py      evaluate() -- pure, deterministic, no I/O
  runner.py         Corpus + BudgetGuard + run_case()
  providers.py      Claude CLI / Codex CLI (MCP bridge) process adapters
  subject_tool.py   the socket client a subject calls (via Bash, or via...)
  mcp_bridge.py     ...this stdio MCP tool, for a Codex subject
  factorial_runtime.py host-owned static/dynamic action state
  factorial_design.py  split, freeze, qualification, and paired scoring
  factorial.py         staged experiment CLI
tests/
  test_pipeline.py  end-to-end: build a corpus, run a scripted controller,
                     score the trace -- proves the modules still work
                     together after extraction, not just that they import
```

The modules support normal package imports. `evaluator.py` retains a direct
script fallback because it re-executes **itself** as a subprocess
(`python3 -B -E -P -I -X pycache_prefix=<throwaway>`) to verify its own
source hasn't been patched before scoring anything with it — see that
module's docstring for why this matters and why the check has to run inside
the child, not the parent. The fallback finds `contract.py` next to the
directly executed evaluator. Installed and checkout users should import the
package normally:

```python
from evidence_evaluator.contract import CASE_VERSION, GOLD_VERSION
from evidence_evaluator.runner import Corpus, run_case
from evidence_evaluator.evaluator import evaluate
```

## Quickstart

```python
from pathlib import Path

from evidence_evaluator.contract import CASE_VERSION, GOLD_VERSION
from evidence_evaluator.runner import Corpus, run_case
from evidence_evaluator.evaluator import evaluate

corpus = Corpus(Path("your/corpus/docs"))

case = {"contract_version": CASE_VERSION, "id": "T01", "query": "...",
        "condition": "direct-handoff", "handoff_path": "HANDOFF.md"}
gold = {"contract_version": GOLD_VERSION, "case_id": "T01",
        "handoff_path": "HANDOFF.md",
        "expected_paths": ["HANDOFF.md", "DESIGN.md"],
        "critical_paths": ["DESIGN.md"],       # must be a subset of expected_paths
        "expected_authority": ["DESIGN.md"],
        "claims": [{"claim_id": "c1", "support_ranges": [
            {"path": "DESIGN.md", "start": 1, "end": 4}]}],
        # Each *_terms entry is OR-of-AND-groups. An omitted or empty list is
        # vacuously UNsatisfiable by design (an empty expectation must not
        # manufacture a pass), so `full_hard_gate` stays False until you
        # supply a real term for every dimension you want it to gate on.
        "current_state_terms": [["approach"]],
        "next_action_terms": [["done"]],
        "stop_condition_terms": [["found"]],
        "is_absent": False}

def my_controller(observation):
    ...  # your own logic, or wire it to providers.run_claude_cli /
         # providers.run_codex_mcp_cli for a live model subject
    return {"action": "read_candidate", "target": "HANDOFF.md", ...}

trace = run_case(case, my_controller, corpus, arm="my-run")
result = evaluate(trace, gold, case)
print(result["full_hard_gate"], result["failure_codes"])
```

See `tests/test_pipeline.py` for a complete, runnable version of the above,
including cases that trigger `R1` (critical path never read) and `C4`
(cited a path never actually read).

## Running the live-agent adapters

`providers.run_claude_cli` and `providers.run_codex_mcp_cli` share a
signature: `(subject, socket_path, prompt, schema_name, config, *,
project_root, host_control, run_name)`. Both:

1. Start a fresh, sandboxed subprocess with no memory of prior runs.
2. Give the subject exactly one way to act — `Bash` running
   `subject_tool.py` for Claude, or the `handoff_action` MCP tool
   (`mcp_bridge.py`) for Codex — both of which speak the same Unix-socket
   JSON protocol your own host process listens on (`subject_tool.request`).
3. Validate the returned payload against a JSON Schema before it's trusted.

`providers.py`'s Seatbelt profile (`seatbelt_profile_v2`) is macOS-specific
(`sandbox-exec`). Port `home_leak_denies()`'s deny-list concept — prior
session transcripts and account config living outside the corpus you meant
to expose — to your platform's process sandbox if you're not on macOS.

`codex-mcp-cli` needs `fastmcp` installed in the interpreter that launches
`mcp_bridge.py` (not in the evaluated subject's own environment): `pip
install evidence-evaluator[codex-mcp]`.

## Tests

```bash
python3 -m pytest tests/ -q
```

52 collected tests, no network, no model calls, no external files beyond a
`tmp_path` fixture corpus built inline:

- `test_pipeline.py` (5) — end-to-end: build a corpus, run a scripted
  controller, score the trace.
- `test_failure_codes.py` (11) — one negative test per failure code
  `evaluate()` can emit. Added after a mutation test showed a fully vacuous
  `evaluate()` passed 3 of the original 5.
- `test_clean_judge.py` (5) — tampers with `evaluator.py` on disk and asserts
  on real subprocess behavior. Slower by design: the subprocess boundary *is*
  the thing under test, so mocking it would test nothing.
- `test_vault_retrieval_core.py` and `test_vault_retrieval_transports.py` —
  profile policy, canonical identity, graph traversal, Obsidian-output
  validation, CLI/MCP parity, and read-only transport behavior.
