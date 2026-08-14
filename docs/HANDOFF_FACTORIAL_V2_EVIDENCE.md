# Handoff factorial v2 operational evidence

- Operational recovery ID: `HFX2-AUG14`
- Entry handoff: [[HANDOFF_FACTORIAL_V2]]
- Evidence role: canonical current-state authority for operational recovery

## Current state

State code: `READY_FOR_DEVELOPMENT_SCREEN`.

Transport qualification is 6/6 accepted with zero invalid runs. The current
factorial freeze digest is
`dab2ebf9cbee88daad8578fa789bce49d998f0611c92f6f1e5d96fba25b8d9fa`.
The post-freeze `DEV-01/S_DYNAMIC` canary attempt 8 passed the full hard gate,
critical-path recall 1.0, exact authority hit, and state, next-action, and stop
reconstruction. The 16-cell development screen has not run.

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
reconstruction only. The ignored `private_eval` corpus and `results` artifacts
must not be published. This note does not authorize mutation of frozen cases,
gold, harness code, or the freeze receipt.
