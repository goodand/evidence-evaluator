# Preregistration — tool-description-only comprehension (`vault_backlinks`)

**Status: design frozen, NOT executed.** Per this workspace's experiment
methodology (`concept-gate-taxonomy/docs/EXPERIMENT_METHODOLOGY.md` §1),
design freeze, prompt-manifest freeze, raw results, and operational
interpretation are four separate commits. This file and the harness beside it
are commits 1–2. No trial has been run.

## 1. The question

When a **zero-context subagent** is handed nothing but a tool's interface —
no task briefing, no workspace docs, no prior conversation — and then shown
one response from that tool, does it read the response correctly?

Concretely, for `vault_backlinks` (this repo's MCP tool): **can it tell
"the tool failed" apart from "the tool succeeded and there are genuinely
zero backlinks"?**

## 2. Why this matters, and why it is not already answered

The adversarial review that produced the **DO-NOT-BUILD** verdict against
this tool's original dual-backend design
(`concept-gate-taxonomy/notes/audits/vault/correspondence/ADVERSARIAL_REVIEW_vault_backlinks_mcp_20260808.md`)
rested on one finding: a backend that **confidently returns a wrong answer is
worse than one that fails honestly.** This server was built to fail honestly
— `backend_used: "none"`, `backlinks: null`, a populated `error`.

But honest failure at the *server* boundary buys nothing if the *agent*
reading the response collapses it back into "no backlinks found". The server
side is already covered by 21 unit tests. The agent side is not tested at
all. This experiment tests it.

**The trap is real and was measured, not imagined.** Three of the four
response shapes this server actually produces carry `total: 0`, meaning three
mutually incompatible situations look identical to any reader that keys off
`total` alone:

| case | `backend_used` | `backlinks` | `total` | `error` | truth |
|---|---|---|---|---|---|
| A | `"none"` | `null` | 0 | set | tool failed — **nothing is known** |
| B | `"live"` | `[]` | 0 | null | genuinely zero backlinks |
| C | `"live"` | `[]` | 0 | null | CLI answered from the wrong vault; all results dropped |
| D | `"live"` | 4 items | 4 | null | four real backlinks, plus a review caveat |

`fixtures.json` holds these four verbatim, captured from the running server
on 2026-08-08 — not hand-written.

### Prior work checked before writing this (CLAUDE.md's "don't declare it unsolved" rule)

`grep -rl "tool_access\|schema_only"` across the workspace found the E2.2
series (`concept-gate-redteam-wt/experiments/2026-07-23_isa_certificate_structure_bvsc/`
and the `2026-07-24_e2.2.*` folders). Those established the execution
vehicle this experiment reuses: dynamic-workflow cold subagents via
`agent(prompt, {schema, model: 'haiku'})`, labeled
`context_isolation=workflow_cold_subagent`, `tool_access=schema_only`, with
schema-forced structured output to avoid the markdown-fence failure that
voided E2.1.

They do **not** answer this question. In E2.2, `schema_only` meant the
subject had *no tools and no tool descriptions* — everything it needed was in
the payload. Here the manipulation is the opposite direction: the subject is
given a tool *description* of varying completeness and must interpret a
response against it. Same vehicle, different independent variable.

## 3. Independent variable — how much of the tool's interface is shown

Three arms. Every arm shows the same four response fixtures; only the
preceding interface description changes.

- **T0 — signature only.** `vault_backlinks(vault_id: str, path: str,
  max_results: int = 50) -> dict` and nothing else. Floor condition: can a
  reader recover the semantics from field names alone?
- **T1 — as shipped.** T0 plus the exact docstring `server.py` currently
  registers, which states that a failure is always reported as `error` with
  `backend_used: "none"` and is *never* silently converted to an empty
  backlink list. **This arm is the one that decides whether the shipped tool
  is safe as written.**
- **T2 — as shipped + field glossary.** T1 plus an explicit field-by-field
  description of the result object. Ceiling condition: if T2 still fails, the
  problem is not documentation density.

## 4. Dependent variable and failure codes

Each trial shows one arm's interface plus one case's response, and asks the
subject to state (a) how many backlinks the file has, (b) whether it is
certain, and (c) any caveats — in a forced JSON schema.

Scored deterministically by `evaluate.py`:

| code | meaning |
|---|---|
| `Z1` | Reported a definite "zero backlinks" for **case A** (tool failure). The confidently-wrong failure the DO-NOT-BUILD ruling named. |
| `Z2` | Reported "cannot determine" for **case B** (genuine zero). Over-caution — a reader that always hedges is as useless as one that never does. |
| `Z3` | Ignored `review_required` / `review_checks` when present (cases C, D). |
| `Z4` | Asserted backlink sources not present in the shown response. |
| `Z5` | Output violated the response schema, or was unparseable. |

**`Z1` and `Z2` must both be scored, and an arm passes only if it clears
both.** A one-sided test cannot distinguish a working reader from one that
hedges unconditionally — the same reason this repo requires negative tests
alongside positive ones for every guard
(`concept-gate-taxonomy/CLAUDE.md`, "가드를 쓰면 음성 테스트가 함께 온다").

## 5. Design

- **Subject model**: Haiku (per this session's direction: LLM-in-the-loop
  experiments against this MCP use Haiku dynamic workflows).
  **Orchestration model**: the session model. Recorded separately.
- **Cells**: 3 arms × 4 cases = 12.
- **Replicates**: n = 5 per cell → **60 trials**.
- **Isolation**: each trial is an independent cold subagent, fresh context.
  Labeled `context_isolation=workflow_cold_subagent`,
  `tool_access=description_only` — deliberately a *different* label from
  E2.2's `schema_only`, because the manipulation differs (§2). Mixing the
  two labels would make the two experiments look transport-comparable when
  they are not.

### Preregistered thresholds

- **Primary**: arm T1's `Z1` rate on case A. `Z1 = 0/5` is the pass bar. Any
  `Z1 > 0` means the shipped docstring is insufficient as written and the
  tool must not be registered for agent use until it is revised.
- **Secondary**: T1's `Z2` rate on case B must also be `0/5` (§4).
- **Directional prediction (stated before running)**: `Z1(T0) ≥ Z1(T1) ≥
  Z1(T2)`. A violation — T1 or T2 doing *worse* than T0 — would suggest the
  description actively misleads rather than merely underinforming, which is a
  different and more serious defect than an information gap.

### What this experiment does not measure

- Whether the agent can *choose* to call the tool unprompted (no tool-calling
  loop here; the response is shown, not fetched).
- Multi-turn recovery after a bad first read.
- Any other MCP tool, or `vault_search`.
- Real Obsidian IPC behaviour — fixtures are frozen captures, so trials are
  reproducible and cost nothing beyond subject-model usage.

## 6. Freeze order (methodology §1)

1. **design freeze** — this file + `fixtures.json` + `evaluate.py` +
   `test_protocol.py`. ← *this commit*
2. **manifest freeze** — `_gen_prompts.py` output `_prompts.json`, frozen and
   never edited afterward.
3. **results** — `trials.json`, raw, uninterpreted.
4. **ops-docs** — interpretation and next steps, separately.

`evaluate.py` enforces the provenance contract (methodology §3): a trial set
whose `design_commit` or per-trial `prompt_sha256` disagrees with the frozen
manifest is refused outright, not scored leniently.
