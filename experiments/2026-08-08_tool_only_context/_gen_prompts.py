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
# Arm interfaces. T1's text is a verbatim copy of what server.py registers --
# `test_protocol.py` asserts that, so this cannot silently drift from the
# shipped tool and quietly measure a docstring that is no longer real.
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

ARMS = {
    "T0": SIGNATURE,
    "T1": f"{SIGNATURE}\n\n{T1_DOCSTRING}",
    "T2": f"{SIGNATURE}\n\n{T1_DOCSTRING}\n\n{T2_GLOSSARY}",
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


def build() -> dict:
    fixtures = json.loads((HERE / "fixtures.json").read_text(encoding="utf-8"))
    prompts = []
    for arm, interface in ARMS.items():
        for case_id, response in fixtures.items():
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
            "design_commit": "PENDING_FREEZE",
            "subject_model": "haiku",
            "replicates_per_cell": 5,
            "context_isolation": "workflow_cold_subagent",
            "tool_access": "description_only",
        },
        "response_schema": RESPONSE_SCHEMA,
        "prompts": prompts,
    }


if __name__ == "__main__":
    manifest = build()
    out = HERE / "_prompts.json"
    out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {out} with {len(manifest['prompts'])} prompts "
          f"({len(ARMS)} arms x {len(manifest['prompts']) // len(ARMS)} cases)")
