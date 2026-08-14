# Handoff factorial v2 operational evidence

- Operational recovery ID: `HFX2-AUG14`
- Entry handoff: [[HANDOFF_FACTORIAL_V2]]
- Evidence role: canonical current-state authority for operational recovery

## Current state

State code: `READY_FOR_DEVELOPMENT_SCREEN`.

The prior transport qualification remains historical and was not overwritten.
The six frozen transport cases were rerun under the current transport surface
with `gpt-5.6-luna`: 6/6 were accepted with zero invalid runs. The append-only
qualification receipt verifies against the current source, results, audits,
model, and frozen private inputs. Its tracked digest is
`6b41b82d36d2c2782bed583f3655af7b9dc9d8c62aa71febd3f341dd0752ca4e`.
The current factorial freeze digest is
`a01569b7a1add4ae0a02ac18882384164617c7da6540c16340db0bdb510d2564`.
The post-freeze `DEV-01/S_DYNAMIC` canary attempt 8 passed the implemented
structured hard gate, critical-path recall 1.0, exact authority hit, and exact
state, next-action, and stop codes under the preceding harness surface. The
16-cell development screen has not run and is now the only authorized next
action.

## Authorized continuation

Next-action code: `RUN_16_CELL_DEVELOPMENT_SCREEN`.

Run only the preregistered development screen: eight development cases across
`S_STATIC` and `S_DYNAMIC`, one replicate each. Preserve every cell, summary,
and `screen-receipt.json` as append-only artifacts.

## Stop conditions

- `STOP_AFTER_SCREEN_RECEIPT`: stop after the screen and its receipt are
  written; inspect the screen decision before any held-out execution.
- `BLOCK_CONFIRM_UNTIL_SCREEN_PIN_COMMITTED`: do not run `confirm` until the
  screen receipt digest is copied into `TRUSTED_SCREEN_RECEIPT_DIGEST` and that
  pin is committed separately.
- `NO_PERFORMANCE_CLAIMS_FROM_CANARY`: do not infer controller, helper,
  interaction, held-out, or vault-wide performance from the one-cell canary.

## Evidence boundary

The canary establishes live provider-to-MCP plumbing and one development
reconstruction only. Its automatic citation check establishes range exposure,
not semantic entailment; a detached low-context review separately checked the
actual prose against those ranges. The ignored `private_eval` corpus and
`results` artifacts must not be published. This note does not authorize
mutation of frozen cases, gold, harness code, or the freeze receipt.
