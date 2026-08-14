# Zero-context MCP handoff canary

## Purpose

Test one narrow claim: can a fresh agent, with no conversation history and no
filesystem tools, use the vault MCP to discover a handoff, read its authority
source, and reconstruct current state, next action, and stop conditions?

This is not a multi-arm retrieval experiment. It does not measure static vs
dynamic workflow, subagent effects, or general recall.

## Subject boundary

`evidence_evaluator.handoff_canary` starts `codex exec --ephemeral` with:

- `--ignore-user-config` and `--ignore-rules`;
- native shell, file, browser, web, app, and multi-agent features disabled;
- one stdio MCP server;
- exactly `vault_search`, `vault_read`, and `vault_backlinks` enabled;
- an explicit model, timeout, output schema, and maximum MCP-call budget.

The case gives only a project identifier and question. It does not reveal the
handoff path. The private gold is never placed in the subject directory or MCP
environment.

## Supervisor evidence

Set by the runner, `EVIDENCE_MCP_AUDIT_LOG` records one JSONL row per tool
attempt. Search rows contain returned paths and artifact digest. Read rows
contain canonical path, line range, and content/document hashes. Source content
is not logged. The evaluator accepts a citation only when its path and line
range fit inside a successful `vault_read` row.

## Outcomes

1. **Runtime**: provider completed, MCP call count is within budget, search and
   read both occurred, and no forbidden/native tool event or MCP error exists.
2. **Retrieval**: search discovered the handoff, all critical paths were read,
   and at least one exact authority path was hit.
3. **Reconstruction**: state, next-action, and stop codes match frozen gold and
   every claim has a supervisor-supported citation.

Timeout, MCP startup failure, or an unavailable permission lane is an invalid
run, not retrieval score zero. `vault_backlinks` is allowed but not mandatory
for this canary.

## Acceptance

The result is accepted only if all three outcomes pass. Even then, do not claim
arm effects, multi-case generalization, vault-wide recall, or backlink
necessity. Producer and curator are the same person for this development
canary; gold was frozen before the live subject and that limitation remains.

## Verification

```bash
python3 -m pytest tests/test_handoff_canary.py -q
python3 -m pytest tests/test_vault_retrieval_transports.py -q
python3 -m pytest tests/ -q
```

The negative set covers no MCP use, search-only behavior, missing authority,
unread citations, unrelated/native tool events, call-budget overflow, and
provider timeout. The scripted E2E traverses the same runner and assessment
path without a model call.
