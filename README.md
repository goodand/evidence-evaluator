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
| Protocol machinery | — | `run_live_phase_c.py`'s qualification gating, `FROZEN_SURFACE_FILES`, the paid-run refusal guards, `PREREGISTRATION.md` |

The right-hand column is research-protocol machinery specific to that one
experiment's risk management (should *this* paid model call happen right
now, given *this* repo's frozen-surface pins) — not a generic evaluator
concept. Don't expect to find it here; wire your own gating around the
engine below if you need it.

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

## Layout and why imports are flat

```
evidence_evaluator/
  contract.py      case/gold/trace/subagent-output schema + validators
  evaluator.py      evaluate() -- pure, deterministic, no I/O
  runner.py         Corpus + BudgetGuard + run_case()
  providers.py      Claude CLI / Codex CLI (MCP bridge) process adapters
  subject_tool.py   the socket client a subject calls (via Bash, or via...)
  mcp_bridge.py     ...this stdio MCP tool, for a Codex subject
tests/
  test_pipeline.py  end-to-end: build a corpus, run a scripted controller,
                     score the trace -- proves the modules still work
                     together after extraction, not just that they import
```

The modules import each other with flat names (`from contract import ...`),
not `evidence_evaluator.contract`. This is deliberate, not an oversight:
`evaluator.py` re-executes **itself** as a subprocess
(`python3 -B -E -P -I -X pycache_prefix=<throwaway>`) to verify its own
source hasn't been patched before scoring anything with it — see that
module's docstring for why this matters and why the check has to run inside
the child, not the parent. That subprocess launches as a bare script, so it
needs `contract.py` sitting next to it on a flat `sys.path`, which package-
relative imports would not survive. `pyproject.toml` exists for versioning
and dependency metadata, not because `pip install`-ing this makes
`evidence_evaluator.contract` importable in the usual sense — add the
`evidence_evaluator/` directory itself to `sys.path`:

```python
import sys
sys.path.insert(0, "/path/to/evidence-evaluator/evidence_evaluator")
from contract import CASE_VERSION, GOLD_VERSION
from runner import Corpus, run_case
from evaluator import evaluate
```

## Quickstart

```python
import sys
from pathlib import Path

sys.path.insert(0, "evidence-evaluator/evidence_evaluator")
from contract import CASE_VERSION, GOLD_VERSION
from runner import Corpus, run_case
from evaluator import evaluate

corpus = Corpus(Path("your/corpus/docs"))

case = {"contract_version": CASE_VERSION, "id": "T01", "query": "...",
        "condition": "direct-handoff", "handoff_path": "HANDOFF.md"}
gold = {"contract_version": GOLD_VERSION, "case_id": "T01",
        "handoff_path": "HANDOFF.md", "expected_paths": [...],
        "critical_paths": [...], "expected_authority": [...],
        "claims": [...], "is_absent": False}

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

5 tests, no network, no model calls, no external files beyond a `tmp_path`
fixture corpus built inline.
