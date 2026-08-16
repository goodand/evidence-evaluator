# Backend parity check — 2026-08-15

`DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md` §8 condition 5 (evidence-evaluator
package): before the harness can be retired, representative live-vault
queries must be compared against it and material regressions recorded, not
hidden. This is that record for the new `evidence`-backed adapter
(`obsidian_backend_evidence.py`), run with `scripts/parity_check_backends.py`
against every vault in the real registry on this machine — not synthetic
fixtures.

## Result: 10/15 exact match, 5/15 differ with a known, understood cause

| Vault | Paths checked | Result |
|---|---|---|
| `project-in-progress` | 5 (including two paths with 6–11 backlinks each) | **5/5 exact match**, including list order |
| `perfect-structure` | 5 | **5/5 match** (all empty both sides) |
| `goodantak` | 5 | **5/5 differ** |

## The `goodantak` difference — root cause, not a mystery

Both backends see the same underlying condition: the Obsidian CLI answers
`Error: File "<path>" not found.` for every sampled path in this vault
(pre-existing, unrelated to this adapter — see `obsidian_backend.py`'s own
module docstring on symlink/`cwd` defects in this exact vault).

- **harness path**: `fetch_backlinks()` only checks `returncode != 0` or the
  literal substring `"unable to find Obsidian"` — neither matches, so the
  call is treated as successful. `parse_cli_output()` then fails to parse
  the error text as JSON and falls back to one string per line:
  `["Error: File \"README.md\" not found."]`. `contracts.py` turns that
  string into `{"file": "Error: File \"README.md\" not found."}`, which
  then fails `exists_under_root()` and is silently dropped as
  `dropped_by_reason.out_of_scope`. The empty result you see is an
  **accidental side effect of an unrelated security filter**, not
  intentional "not found" handling.
- **evidence path**: `ObsidianCliBackend._looks_like_error()` explicitly
  matches lines starting with `error`/`failed`/`unable`/etc., so this
  response is recognized as a real CLI error and `backlinks_only()` reports
  `available=False`. `fetch_backlinks()` then raises `ObsidianUnavailable`.

**This is not a regression to fix before adopting the new backend — it is
arguably the new backend behaving MORE correctly.** `contracts.py`'s own
module docstring states the rule this whole server exists to enforce: "never
turn a failure into a silent empty/zero result that reads the same as
'confirmed no backlinks'." The harness path currently does exactly that for
this vault, via a filter that was never designed to serve as error
detection. Recorded here per §8's requirement rather than silently accepted
or silently "fixed" by loosening the new backend's error detection to match
the old accidental behavior.

## Separately known, unrelated to this check

`link_count` is not compared above and is a known, separate gap: the
`evidence` backend always reports the fallback default (`1`), never a real
per-file count (see `obsidian_backend_evidence.py`'s module docstring, and
the poison test in `tests/test_obsidian_backend_evidence.py` that fails
loudly if this is ever silently fixed without updating this note).

## What this does NOT establish

- Whether `VAULT_BACKLINKS_BACKEND=evidence` should become the default —
  that is a decision for whoever owns this migration, informed by the two
  findings above, not something this check settles.
- Coverage beyond 15 sampled paths across 3 vaults on one machine.
