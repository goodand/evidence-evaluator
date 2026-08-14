# Zero-context MCP handoff canary result — 2026-08-14

## Scope

One case, one fresh Codex subject, one fixed workflow. This result tests whether
the subject can discover and reconstruct HMC-AUG14 through the read-only vault
MCP. It does not compare models, workflow arms, or subagent use.

Frozen inputs:

- `../../notes/audits/vault/handoff-mcp-canary-20260814.md`
- `../../notes/audits/vault/handoff-mcp-canary-authority-20260814.md`
- ignored `private_eval/handoff-mcp-canary-v1/case.json`
- ignored `private_eval/handoff-mcp-canary-v1/gold.json`

## Attempts

1. Attempt 1: invalid before model execution. The generic provider serialized
   the MCP environment as JSON, while Codex config requires a TOML inline map.
   The provider was corrected and the invalid artifact was preserved.
2. Attempt 2: invalid in the managed permission lane. Codex app-server startup
   returned `Operation not permitted`; Retrieval was not scored.
3. Attempt 3: host-capable lane, accepted.

## Attempt 3 result

| Layer | Result | Evidence |
|---|---|---|
| Runtime | PASS | 3 MCP calls; search 1, read 2; no MCP errors or forbidden events |
| Retrieval | PASS | handoff discovered; critical-path Recall 1.0; exact authority hit |
| Reconstruction | PASS | state, next action, both stop conditions, and all citations verified |

The subject read exactly the frozen handoff and authority note. Every citation
fit inside a supervisor-recorded `vault_read` range. The audit JSONL contains
paths, ranges, and hashes but no source content.

The compact search result reduced this fresh run relative to the earlier direct
MCP smoke, but the provider still reported 93,596 input tokens. The prior smoke
was roughly 280k; this is a directional transport improvement, not a controlled
cost comparison.

## Interpretation boundary

Established: the current Codex host lane can execute provider → MCP search →
bounded reads → structured response → deterministic assessment end to end for
this case.

Not established: arm effect, multi-case generalization, vault-wide recall,
backlink necessity, or behavior in the managed lane. The managed-lane failure
is BLOCKED/invalid-run, not retrieval score zero.
