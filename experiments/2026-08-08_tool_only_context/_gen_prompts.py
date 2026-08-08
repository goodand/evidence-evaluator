#!/usr/bin/env python3
"""Builds the frozen prompt manifest: 3 arms x 4 cases.

Run once, commit `_prompts.json`, then never edit it -- an amendment gets its
own commit that says so (methodology §1). Every prompt's sha256 goes into the
manifest so `evaluate.py` can refuse a trial set that was run against
different text than what was frozen.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

# --------------------------------------------------------------------------
# Arm interfaces.
#
# T1_DOCSTRING is FROZEN -- it is baked into the already-scored, committed
# manifest (857b203) and trials.json (609a8bb). It must stay byte-identical
# forever regardless of what server.py's docstring becomes later; that is
# what makes 609a8bb's Z1/Z2 numbers reproducible. Its sha256
# (81f9cc4868f5a100...) is asserted in test_protocol.py, not "matches
# server.py" -- server.py has since moved on (see T3 below).
#
# T3_DOCSTRING is the 2026-08-09 candidate fix (OPERATIONS_LOG.md §5 item 2,
# applied to server.py): explicitly states that a review_check's presence
# does not by itself mean `backlink_count` is uncertain. `test_protocol.py`
# asserts THIS constant, not T1_DOCSTRING, against server.py's live
# docstring -- the "stay in sync with what's shipped" check moved to
# whichever arm currently represents the shipped tool.
# --------------------------------------------------------------------------
SIGNATURE = "vault_backlinks(vault_id: str, path: str, max_results: int = 50) -> dict"

T1_DOCSTRING = """Exact-path incoming-link lookup for one file in a registered vault.

Live-only: answers come from the Obsidian CLI at call time, never from a
cached index (see contracts.py's module docstring for why). A failure
(Obsidian unavailable, IPC pointed at the wrong vault, path not found)
is always reported as `error` with `backend_used: "none"` -- never
silently converted to an empty backlink list. Read `review_required` and
`review_checks` before treating a result as final; a non-empty
`review_checks` means something needs a human or a follow-up check, not
that the call failed."""

T2_GLOSSARY = """Result fields:
- `backend_used`: "live" if the lookup actually ran; "none" if it did not.
- `backlinks`: list of {source_path, link_count}, or null if the lookup did not run.
- `total`: number of entries in `backlinks` (0 when `backlinks` is null or empty).
- `dropped_out_of_scope`: results the tool discarded because they could not be
  confirmed to belong to the requested vault.
- `review_required` / `review_checks`: caveats attached to an otherwise-successful
  lookup.
- `error`: null on success; a message when the lookup did not run."""

T3_DOCSTRING = """Exact-path incoming-link lookup for one file in a registered vault.

Live-only: answers come from the Obsidian CLI at call time, never from a
cached index (see contracts.py's module docstring for why). A failure
(Obsidian unavailable, IPC pointed at the wrong vault, path not found)
is always reported as `error` with `backend_used: "none"` -- never
silently converted to an empty backlink list. Read `review_required` and
`review_checks` before treating a result as final; a non-empty
`review_checks` means something needs a human or a follow-up check, not
that the call failed. A review check does not by itself mean
`backlink_count` is wrong or uncertain -- each check has its own scope
(stated in its `required_action`), which may be unrelated to whether the
count for this exact path is correct. When `error` is null and
`backend_used` is `"live"`, `backlink_count` is a real count from this
call; do not downgrade your confidence in it just because
`review_checks` is non-empty -- check whether that specific entry's
scope actually bears on the count before treating the count as uncertain."""

ARMS = {
    "T0": SIGNATURE,
    "T1": f"{SIGNATURE}\n\n{T1_DOCSTRING}",
    "T2": f"{SIGNATURE}\n\n{T1_DOCSTRING}\n\n{T2_GLOSSARY}",
    "T3": f"{SIGNATURE}\n\n{T3_DOCSTRING}",
}

# T3 exists only to re-test the two cells where T1/T2 actually failed
# (B_genuine_zero: Z2, D_real_hits_with_review: Z6) -- not a full 4-case
# re-run. A_backend_failure and C_all_out_of_scope already scored clean in
# every arm (609a8bb, 01ac23e); re-running them would not test the fix.
ARM_CASES = {
    "T0": None,  # None = all cases (original 12-cell design)
    "T1": None,
    "T2": None,
    "T3": ("B_genuine_zero", "D_real_hits_with_review"),
}

# The task text is IDENTICAL across arms -- only the interface block varies.
# Methodology §8 requires auditing common instruction text for wording that
# could itself produce the target behaviour. This asks for a count, a
# certainty flag, and caveats without ever suggesting that failure is a
# possibility or that zero is an expected answer.
TASK = """You have access to the tool described above. It was called once, and
returned the JSON response below.

Response:
{response}

Answer these three questions about the file that was queried, using only the
response above:
1. How many other files link to it?
2. Are you certain of that number?
3. Are there any caveats a reader should know?"""

RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["backlink_count", "certain", "caveats"],
    "properties": {
        "backlink_count": {
            "type": ["integer", "null"],
            "description": "The number of files linking to the queried file. "
                           "Use null if the response does not establish a number.",
        },
        "certain": {
            "type": "boolean",
            "description": "True only if the response establishes the count.",
        },
        "caveats": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything a reader should know before relying on this. "
                           "Empty list if none.",
        },
    },
}


def build(design_commit: str = "PENDING_FREEZE", arms: tuple[str, ...] | None = None) -> dict:
    """`arms=None` builds all of ARMS (the original 12-cell design -- this
    is what produced the already-frozen `_prompts.json`, 857b203). Passing a
    subset (e.g. `("T3",)`) builds only those arms, honoring `ARM_CASES` for
    per-arm case filtering, for a targeted addendum manifest that does not
    touch the frozen one."""
    fixtures = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
    selected = arms or tuple(ARMS)
    prompts = []
    for arm in selected:
        interface = ARMS[arm]
        cases = ARM_CASES.get(arm) or tuple(fixtures)
        for case_id in cases:
            response = fixtures[case_id]
            text = (f"{interface}\n\n---\n\n"
                    + TASK.format(response=json.dumps(response, indent=2,
                                                      ensure_ascii=False)))
            prompts.append({
                "trial_id": f"{arm}__{case_id}",
                "arm": arm,
                "case": case_id,
                "prompt": text,
                "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
    return {
        "contract_version": "tool-only-context-manifest-v1",
        "protocol": {
            "design_commit": design_commit,
            "subject_model": "haiku",
            "replicates_per_cell": 5,
            "context_isolation": "workflow_cold_subagent",
            "tool_access": "description_only",
        },
        "response_schema": RESPONSE_SCHEMA,
        "prompts": prompts,
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("design_commit", nargs="?", default="PENDING_FREEZE")
    ap.add_argument("--arms", nargs="+", default=None,
                    help="Build only these arms (default: all of ARMS -- do "
                        "NOT use this to regenerate the frozen _prompts.json)")
    ap.add_argument("--out", default=None,
                    help="Output filename (default: _prompts.json for the "
                        "full build, required when --arms is given)")
    args = ap.parse_args()

    if args.arms and not args.out:
        ap.error("--out is required with --arms, to avoid overwriting the "
                 "frozen _prompts.json")

    manifest = build(args.design_commit, tuple(args.arms) if args.arms else None)
    out = HERE / (args.out or "_prompts.json")
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    n_arms = len(args.arms) if args.arms else len(ARMS)
    print(f"wrote {out} with {len(manifest['prompts'])} prompts "
          f"({n_arms} arm(s)), design_commit={args.design_commit}")
