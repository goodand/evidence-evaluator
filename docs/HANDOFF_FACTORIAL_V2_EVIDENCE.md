# Handoff factorial v2 operational evidence

- Operational recovery ID: `HFX2-AUG14`
- Entry handoff: [[HANDOFF_FACTORIAL_V2]]
- Codex issue log: [[CODEX_SESSION_ISSUE_LOG_20260814]]
- Evidence role: canonical current-state authority for operational recovery

## Current state

State code: `SCREEN_COMPLETE_CONFIRM_PINNED`.

The prior transport qualification remains historical and was not overwritten.
The six frozen transport cases were rerun under the current transport surface
with `gpt-5.6-luna`: 6/6 were accepted with zero invalid runs. The append-only
qualification receipt verifies against the current source, results, audits,
model, and frozen private inputs. Its tracked digest is
`6b41b82d36d2c2782bed583f3655af7b9dc9d8c62aa71febd3f341dd0752ca4e`.
The current factorial freeze digest is
`a01569b7a1add4ae0a02ac18882384164617c7da6540c16340db0bdb510d2564`.
The 16-cell development screen completed with zero invalid runs. Dynamic
improved three paired cases and regressed none; false absence and premature
stop were both zero. The gate selected `FULL_2X2`. The screen receipt digest
`40027887b71d7bc23b20bb7b397233c4a9c492440f6ee3a2c9dc934b995f6568`
is pinned in commit `21e2f2a` and the public scorer reverified it.

## Authorized continuation

Next-action code: `RUN_HELD_OUT_FULL_2X2_CONFIRM`.

Run the preregistered held-out confirm stage: eight held-out cases across all
four arms and three replicates. Do not change the frozen harness, cases, gold,
model, screen artifacts, or trusted pins before that run.

## Stop conditions

- `NO_TUNING_AFTER_SCREEN`: do not modify the harness or evaluation assets in
  response to development-screen outcomes before held-out confirmation.
- `PRESERVE_SCREEN_RECEIPT_AND_PIN`: do not overwrite the screen artifacts or
  change the trusted receipt digest.
- `NO_HELD_OUT_CLAIMS_BEFORE_CONFIRM`: screen results do not establish held-out,
  subagent, or interaction effects.

## Evidence boundary

The canary establishes live provider-to-MCP plumbing and one development
reconstruction only. Its automatic citation check establishes range exposure,
not semantic entailment; a detached low-context review separately checked the
actual prose against those ranges. The ignored `private_eval` corpus and
`results` artifacts must not be published. This note does not authorize
mutation of frozen cases, gold, harness code, or the freeze receipt.
