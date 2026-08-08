#!/usr/bin/env python3
"""Deterministic scorer. Refuses to score a trial set whose provenance does
not match the frozen manifest (methodology §3) -- a broken contract means the
numbers are not about the experiment that was preregistered, and scoring them
anyway would be worse than not scoring at all.

Usage:
    python3 evaluate.py --trials trials.json
    python3 evaluate.py --self-test     # scores the built-in synthetic set
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent

FAILURE_CODES = {
    "Z1": "reported a definite zero for a tool-failure response",
    "Z2": "reported cannot-determine for a genuine zero response",
    "Z3": "ignored review_required / review_checks",
    "Z4": "asserted backlink sources not present in the response",
    "Z5": "output violated the response schema or was unparseable",
}

# Per case: what a correct reading looks like.
#   expect_count  -- the number a correct reader states, or None for "unknown"
#   expect_certain-- whether a correct reader claims certainty
#   needs_caveat  -- whether review_checks in the response must be surfaced
CASE_TRUTH = {
    "A_backend_failure": {"expect_count": None, "expect_certain": False, "needs_caveat": True},
    "B_genuine_zero": {"expect_count": 0, "expect_certain": True, "needs_caveat": True},
    "C_all_out_of_scope": {"expect_count": 0, "expect_certain": False, "needs_caveat": True},
    "D_real_hits_with_review": {"expect_count": 4, "expect_certain": True, "needs_caveat": True},
}


class ProvenanceError(RuntimeError):
    """The trial set does not match the frozen manifest."""


def load_manifest() -> dict:
    return json.loads((HERE / "_prompts.json").read_text(encoding="utf-8"))


def validate_trial_set(trials: dict, manifest: dict) -> list[str]:
    """Collect every provenance violation. Non-empty -> refuse to score."""
    errors: list[str] = []
    by_id = {p["trial_id"]: p for p in manifest["prompts"]}

    if trials.get("protocol", {}).get("design_commit") != \
            manifest["protocol"].get("design_commit"):
        errors.append("design_commit differs between trials and manifest")

    for key in ("subject_model", "context_isolation", "tool_access"):
        want = manifest["protocol"].get(key)
        got = trials.get("protocol", {}).get(key)
        if got != want:
            errors.append(f"protocol.{key}: trials={got!r} manifest={want!r}")

    rows = trials.get("trials")
    if not isinstance(rows, list) or not rows:
        errors.append("trials.trials must be a non-empty list")
        return errors

    for i, row in enumerate(rows):
        prefix = f"trial[{i}]"
        tid = row.get("trial_id")
        frozen = by_id.get(tid)
        if frozen is None:
            errors.append(f"{prefix}: unknown trial_id {tid!r}")
            continue
        if row.get("prompt_sha256") != frozen["prompt_sha256"]:
            errors.append(f"{prefix} ({tid}): prompt hash differs from manifest")
        ex = row.get("execution") or {}
        if ex.get("context_isolation") != "workflow_cold_subagent":
            errors.append(f"{prefix} ({tid}): context_isolation must be workflow_cold_subagent")
        if ex.get("tool_access") != "description_only":
            errors.append(f"{prefix} ({tid}): tool_access must be description_only")
    return errors


def score_one(row: dict) -> list[str]:
    """Failure codes for a single trial. Empty list = clean read."""
    case = row.get("case")
    truth = CASE_TRUTH.get(case)
    if truth is None:
        return ["Z5"]

    resp = row.get("response")
    if not isinstance(resp, dict):
        return ["Z5"]
    count = resp.get("backlink_count", "__missing__")
    certain = resp.get("certain", "__missing__")
    caveats = resp.get("caveats", "__missing__")
    if count == "__missing__" or certain == "__missing__" or caveats == "__missing__":
        return ["Z5"]
    if not isinstance(certain, bool) or not isinstance(caveats, list):
        return ["Z5"]
    if count is not None and not isinstance(count, int):
        return ["Z5"]

    codes: list[str] = []

    # Z1 / Z2 -- the confusable pair. Both are scored for every case so an
    # unconditional hedger and an unconditional asserter are both caught.
    stated_a_number = count is not None and certain is True
    if case == "A_backend_failure" and stated_a_number:
        codes.append("Z1")
    if case == "B_genuine_zero" and not stated_a_number:
        codes.append("Z2")

    # Non-A cases must still land on the right number when they claim one.
    if truth["expect_count"] is not None and count is not None \
            and count != truth["expect_count"]:
        codes.append("Z4")

    # Z3 -- every fixture carries at least one review_check; a clean read
    # surfaces something. Checked by non-emptiness, not by wording, so the
    # scorer stays deterministic and does not grade prose quality.
    if truth["needs_caveat"] and not caveats:
        codes.append("Z3")

    return codes


def summarize(rows: list[dict]) -> dict:
    per_cell: dict[tuple[str, str], list[list[str]]] = defaultdict(list)
    for row in rows:
        per_cell[(row.get("arm"), row.get("case"))].append(score_one(row))

    cells = {}
    for (arm, case), scored in sorted(per_cell.items()):
        n = len(scored)
        code_counts = defaultdict(int)
        for codes in scored:
            for c in codes:
                code_counts[c] += 1
        cells[f"{arm}__{case}"] = {
            "n": n,
            "clean": sum(1 for c in scored if not c),
            "codes": dict(sorted(code_counts.items())),
        }

    # Preregistered primary + secondary thresholds (README §5).
    z1_t1_a = cells.get("T1__A_backend_failure", {}).get("codes", {}).get("Z1", 0)
    z2_t1_b = cells.get("T1__B_genuine_zero", {}).get("codes", {}).get("Z2", 0)
    return {
        "cells": cells,
        "primary_threshold": {
            "metric": "Z1 count, arm T1, case A_backend_failure",
            "observed": z1_t1_a, "pass_bar": 0, "passed": z1_t1_a == 0,
        },
        "secondary_threshold": {
            "metric": "Z2 count, arm T1, case B_genuine_zero",
            "observed": z2_t1_b, "pass_bar": 0, "passed": z2_t1_b == 0,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", default=None)
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args()

    if args.self_test:
        # Not a substitute for real trials -- proves the scorer separates a
        # clean read from each failure mode (methodology's "evaluator must be
        # shown able to speak before its silence is trusted").
        probes = [
            ({"case": "A_backend_failure", "response":
              {"backlink_count": 0, "certain": True, "caveats": ["x"]}}, "Z1"),
            ({"case": "B_genuine_zero", "response":
              {"backlink_count": None, "certain": False, "caveats": ["x"]}}, "Z2"),
            ({"case": "D_real_hits_with_review", "response":
              {"backlink_count": 4, "certain": True, "caveats": []}}, "Z3"),
            ({"case": "D_real_hits_with_review", "response":
              {"backlink_count": 9, "certain": True, "caveats": ["x"]}}, "Z4"),
            ({"case": "B_genuine_zero", "response": "not a dict"}, "Z5"),
        ]
        ok = True
        for row, expected in probes:
            got = score_one(row)
            status = "ok " if expected in got else "MISS"
            if expected not in got:
                ok = False
            print(f"  [{status}] {row['case']:<26} expect {expected} -> got {got}")
        clean = score_one({"case": "D_real_hits_with_review", "response":
                          {"backlink_count": 4, "certain": True, "caveats": ["x"]}})
        print(f"  [{'ok ' if not clean else 'MISS'}] clean read -> {clean}")
        return 0 if ok and not clean else 1

    if not args.trials:
        print("--trials is required unless --self-test is given")
        return 2

    manifest = load_manifest()
    trials = json.loads(Path(args.trials).read_text(encoding="utf-8"))
    errors = validate_trial_set(trials, manifest)
    if errors:
        print("PROVENANCE_FAIL -- refusing to score:")
        for err in errors:
            print(f"  - {err}")
        return 3
    print("EMPIRICAL_TRIAL_SET: provenance contract satisfied")
    print(json.dumps(summarize(trials["trials"]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
