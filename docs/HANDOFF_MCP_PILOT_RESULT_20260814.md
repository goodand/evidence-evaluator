# Handoff MCP development pilot — 2026-08-14

## Scope

Three one-shot zero-context Codex cases exercised the same read-only MCP
harness. This was a development pilot used to find harness defects, not a
confirmatory model or workflow comparison.

| Case | Retrieval shape | MCP calls | Runtime | Retrieval | Reconstruction |
|---|---|---:|---|---|---|
| HMC-01 | direct project identifier | 3 | PASS | PASS | PASS |
| HMC-02-GRAPH | query vocabulary in entry MOC; follow handoff to authority | 3 | PASS | PASS after Amendment D1 | PASS |
| HMC-03-STALE | superseded handoff ranked first; current authority required | 4 | PASS | PASS | PASS |

All three final deterministic assessments have critical-path Recall 1.0,
navigation discovery Recall 1.0 when applicable, an exact authority hit, exact
state/action/stop codes, and citations covered by actual MCP reads.

## Defects found while running

### D1 — navigation was scored as mandatory evidence

The original HMC-02 gold required the entry MOC to be read. The subject did not
read it because graph search had already returned the linked handoff, then read
the handoff and authority and reconstructed every claim correctly. Original
score: critical-path Recall 2/3 and FAIL.

This was an evaluator-data defect, not retrieval failure. The original gold and
original result remain preserved. The amended contract separates:

- `navigation_paths`: must be discovered by search;
- `required_read_paths`: handoff and authority evidence that must be read.

Reassessment of the unchanged subject output and unchanged MCP audit passes.

### D2 — reading authority did not prove claims used authority

Before the pilot amendment, a subject could read the authority, emit exact
codes, but cite only a navigation or stale note. The stale case made this
validity gap concrete. Every state, next-action, and stop-condition claim must
now contain at least one citation to a declared authority path. A paired
negative regression demonstrates the old false pass.

### D3 — compact search retained repeated provider warnings

Live search payloads were 8–11KB because Obsidian IPC failure was repeated once
per graph probe. The compact projection now emits provider category plus count,
while `include_diagnostics=true` preserves the full warnings. This affects only
transport size, not retrieval ranking or the full artifact digest.

## Live observations

- HMC-01 provider usage: 93,596 input / 1,395 output tokens.
- HMC-02 provider usage: 82,281 input / 1,359 output tokens.
- HMC-03 provider usage: 110,319 input / 1,550 output tokens.
- HMC-03 correctly read the stale handoff, current handoff, and current
  authority, then rejected the destructive stale instruction.
- No run used `vault_backlinks`; this pilot establishes no backlink effect.

Token values are observational. Cases and corpus state differ, so they are not
a controlled cost comparison. The repeated-warning compaction was verified by
unit and transport tests after these live runs and was not used to rewrite
their artifacts.

## Remaining boundary

The pilot establishes that direct, graph-entry, and stale-authority cases are
usable in the host permission lane. It does not establish vault-wide Recall,
static/dynamic workflow effects, subagent effects, or managed-lane operation.
Future confirmatory evaluation needs a separately curated frozen corpus and
cases not used for harness repair.
