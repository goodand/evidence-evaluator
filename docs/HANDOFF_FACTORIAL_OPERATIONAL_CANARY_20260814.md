# Factorial operational handoff canary - 2026-08-14

- Experiment handoff: [[HANDOFF_FACTORIAL_V2]]
- Current-state authority: [[HANDOFF_FACTORIAL_V2_EVIDENCE]]
- Recovery ID: `HFX2-AUG14`

## Purpose

This is a development operational canary over the actual experiment handoff,
not the synthetic factorial corpus. It asks whether a fresh zero-context Codex
subject can use only the read-only Vault MCP to recover current state, the one
authorized next action, and every stop condition after the handoff changes.

The private case, gold, profile, provider transcript, MCP audit, and result are
ignored under `private_eval/` and `results/`. They were never exposed through
the subject's MCP surface.

## Attempt 1 - initial operational state

The first subject used exactly one `vault_search` and two `vault_read` calls.
It discovered and read both the handoff and current-state authority and
reconstructed `READY_FOR_DEVELOPMENT_SCREEN`,
`RUN_16_CELL_DEVELOPMENT_SCREEN`, and all three then-current stop codes.
Runtime, Retrieval, and Reconstruction passed.

Artifact SHA-256:

- result: `db173a676c4cae6e15e99aa990de98a9b0005faf54645abc00eb433ac7010183`
- MCP audit: `defb5839433cf3773d768cf7a997f239bbdee253425709d54c03649701d4af86`

## Independent low-context red team

A fresh ephemeral reviewer received a detached public `HEAD`, the result, and
the content-free MCP audit. It did not receive private case, gold, profile, or
prior-session context. It directly verified document hashes, citation ranges,
state, next action, stop conditions, navigation-authority separation, and the
absence of performance overclaim.

It found two implemented defects and one claim boundary:

1. provider metadata counted both started and completed events while the MCP
   audit counted one row per completed call;
2. search audit projection omitted `fallback_used`, `exhaustive`, and
   `terminal_reason`, preventing detached fallback verification;
3. automatic citation scoring proves read-range exposure and exact structured
   codes, not semantic entailment of arbitrary free prose.

The first two were fixed with negative tests. The third was not replaced with
an unvalidated LLM judge; the claim was narrowed and the reviewer separately
checked the actual prose against the cited ranges.

## State transition

Those shared-provider and MCP-audit changes made the historical six-case
transport qualification stale by harness hash. The handoff authority was
therefore changed before another subject run:

- state: `TRANSPORT_REQUALIFICATION_REQUIRED`
- next action: `REQUALIFY_6_TRANSPORT_CASES`
- development screen: blocked until current-harness requalification passes

The prior 6/6 qualification remains historical evidence and must not be
overwritten or relabeled as current authorization.

## Attempt 2 - updated operational state

A second fresh subject again used one search and two reads. It rejected the old
ready-for-screen state and recovered the new blocker, next action, and all
three updated stop codes. Runtime, Retrieval, and Reconstruction passed.

The two runtime provenance channels now agree exactly:

```text
provider completed tools: vault_search, vault_read, vault_read
server audit tools:        vault_search, vault_read, vault_read
```

The detached audit now records the permission-lane boundary:

```text
fallback_used: filesystem
review_required: true
exhaustive: false
terminal_reason: turn-budget-exhausted
```

Artifact SHA-256:

- result: `bf8c624affa61fde77e4b789b0a42e9502d19c611a127f93cc3f51cddbb007e3`
- MCP audit: `10478bb7d3b7bbf57262eff42a052f2c2aa5be9da6f732e92fef50929fdf0a08`

## Attempts 3 and 4 - Luna operational check

Attempt 3 used `gpt-5.6-luna`. Retrieval and reconstruction were correct, but
the runtime was rejected because the provider trace contained an initial
failed `vault_search` call with a malformed `question` argument followed by a
successful retry with `query`. The server audit correctly contained only the
successful call, while the provider summary incorrectly mixed the failed call
into its successful-call list.

The runtime contract now keeps successful and failed provider calls separate.
Successful calls must still exactly match the server audit, failed calls remain
visible, and both consume the fixed call budget. Two regression tests cover a
recovered provider failure and rejection after failed attempts exceed budget.
Attempt 3 remains an immutable failed historical artifact.

Attempt 4 reran the same case with `gpt-5.6-luna`. It used one search and three
reads without a failed provider call. Runtime, Retrieval, and Reconstruction
all passed. It recovered the current state, authorized next action, and all
three stop codes from the handoff and current-state authority.

Artifact SHA-256:

- attempt 3 result: `e6bf63b27b253fbf0332e5d2eca25e62691fa536568dbbd6240c6c1c0b54d7bd`
- attempt 3 MCP audit: `93c28e4f1a530c03569770ea6c487344f5916a9f9e04ba3db3fd4407ba64f5ab`
- attempt 4 result: `0048d93db5052b6712e98f82051d875a7a5e3e469538d7d61835a99db198df18`
- attempt 4 MCP audit: `f21a3a45f224fc185dd5805c95781bec334bd7f0329c4347b135e7a921f81553`

## Verdict and limits

This establishes that one actual experiment handoff can be found and that a
fresh subject follows a changed current-state authority instead of repeating a
previous readiness state. It does not establish static/dynamic arm effects,
subagent effects, vault-wide recall, backlink necessity, or automated semantic
entailment.

Current local verification is 116 passed in the present host-capable lane.
Managed lanes that block `AF_UNIX` must still report the affected checks as
BLOCKED rather than silently treating skips as passes. The next experiment
action remains the six-case transport requalification; the development screen
is blocked.

## Subject model policy

Attempts 1 and 2 used `gpt-5.6-sol` and remain historical artifacts. Future
low-complexity operational handoff subjects use `gpt-5.6-luna`; `sol` is
unnecessarily large for this three-call recovery task. This policy does not
change the model frozen in the separate factorial performance manifest.
Attempt 4 establishes that Luna can complete this one operational case; it
does not establish comparative model performance or multi-case reliability.
