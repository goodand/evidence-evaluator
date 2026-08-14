# Handoff factorial v2 operational evidence

- Operational recovery ID: `HFX2-AUG14`
- Entry handoff: [[HANDOFF_FACTORIAL_V2]]
- Evidence role: canonical current-state authority for operational recovery

## Current state

State code: `TRANSPORT_REQUALIFICATION_REQUIRED`.

The prior transport qualification accepted 6/6 with zero invalid runs, but
changes to `handoff_canary.py`, `providers.py`, and `retrieval/mcp_server.py`
made its harness hashes stale. It is historical evidence, not current
authorization. The current factorial freeze digest is
`a01569b7a1add4ae0a02ac18882384164617c7da6540c16340db0bdb510d2564`.
The post-freeze `DEV-01/S_DYNAMIC` canary attempt 8 passed the implemented
structured hard gate, critical-path recall 1.0, exact authority hit, and exact
state, next-action, and stop codes under the preceding harness surface. The
16-cell development screen has not run and is not currently authorized.

## Authorized continuation

Next-action code: `REQUALIFY_6_TRANSPORT_CASES`.

Rerun the six frozen transport cases with the current harness using fresh
output filenames. Verify that all six are valid and accepted and that the
current harness hashes are recorded before changing readiness to the
development screen.

## Stop conditions

- `BLOCK_DEVELOPMENT_SCREEN_UNTIL_REQUALIFIED`: do not run the 16-cell screen
  until all six transport cases pass under the current harness surface.
- `PRESERVE_PRIOR_QUALIFICATION_AS_HISTORICAL`: do not overwrite or relabel the
  prior 6/6 result; write a new qualification artifact.
- `NO_PERFORMANCE_CLAIMS_FROM_CANARY`: do not infer controller, helper,
  interaction, held-out, or vault-wide performance from the one-cell canary.

## Evidence boundary

The canary establishes live provider-to-MCP plumbing and one development
reconstruction only. Its automatic citation check establishes range exposure,
not semantic entailment; a detached low-context review separately checked the
actual prose against those ranges. The ignored `private_eval` corpus and
`results` artifacts must not be published. This note does not authorize
mutation of frozen cases, gold, harness code, or the freeze receipt.
