#!/usr/bin/env python3
"""Integration probe: run the real server against every registered vault and
check that its *safety* properties hold on real data, not fixtures.

This is not the preregistered experiment (that one measures an LLM reading
tool descriptions -- see README.md). This is the end-to-end check that the
server itself behaves correctly against three live vaults with genuinely
different shapes: one flat, one symlink-heavy, one with neither.

The properties asserted are the ones the DO-NOT-BUILD ruling cared about:
never present an unverified or failed lookup as a confident zero.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "vault_backlinks_mcp"))

from contracts import query_backlinks  # noqa: E402
from registry import load_registry  # noqa: E402


def probe(vault_id: str, path: str, expectation: str) -> dict:
    result = query_backlinks(vault_id, path)
    codes = [c["code"] for c in result["review_checks"]]
    return {
        "vault_id": vault_id, "path": path, "expectation": expectation,
        "backend_used": result["backend_used"], "total": result["total"],
        "dropped_out_of_scope": result["dropped_out_of_scope"],
        "review_required": result["review_required"], "review_codes": codes,
        "error": result["error"],
    }


def main() -> int:
    registry = load_registry()
    rows: list[dict] = []
    failures: list[str] = []

    # 1. Flat real file, links pointing at it -> real answer, no drops.
    if "project-in-progress" in registry:
        r = probe("project-in-progress", "CLAUDE.md", "real backlinks, nothing dropped")
        rows.append(r)
        if r["backend_used"] != "live" or r["total"] < 1 or r["dropped_out_of_scope"]:
            failures.append("project-in-progress/CLAUDE.md did not return a clean real answer")
        if "BASENAME_COLLISION" not in r["review_codes"]:
            failures.append("expected BASENAME_COLLISION (11 CLAUDE.md across worktrees)")

    if "goodantak" in registry:
        # 2. Symlinked path -> must NOT read as a confident zero.
        r = probe("goodantak", "docs/stage3_adaptive_retrieval_recovery_architecture.md",
                  "symlink: flagged, never a bare zero")
        rows.append(r)
        if "SYMLINK_TARGET" not in r["review_codes"]:
            failures.append("symlink path did not raise SYMLINK_TARGET")
        if r["total"] == 0 and not r["review_required"]:
            failures.append("symlink path returned an UNFLAGGED zero -- the exact "
                            "confidently-wrong failure this server exists to prevent")

        # 3. Canonical path for the same note -> the real answer appears.
        r = probe("goodantak",
                  "knowledge/files/markdown/docs/stage3_adaptive_retrieval_recovery_architecture.md",
                  "canonical: real backlinks")
        rows.append(r)
        if r["total"] < 1:
            failures.append("canonical path returned no backlinks (expected >=1)")
        if r["dropped_out_of_scope"]:
            failures.append("canonical path dropped results -- wrong-vault answer leaked in")

    # 4. Cross-vault isolation: a path that exists only in vault A must never
    #    be answered for vault B.
    if "goodantak" in registry:
        r = probe("goodantak", "CLAUDE.md", "not in this vault -> refused, never answered")
        rows.append(r)
        if r["error"] is None:
            failures.append("goodantak/CLAUDE.md was answered; it does not exist there")
        if r["total"]:
            failures.append("goodantak/CLAUDE.md returned backlinks from another vault")

    if "perfect-structure" in registry:
        r = probe("perfect-structure", "README.md", "third vault, no symlinks")
        rows.append(r)
        if r["backend_used"] == "live" and r["total"] == 0 and not r["review_required"]:
            failures.append("perfect-structure/README.md: unflagged zero")

    print(json.dumps({"probes": rows, "failures": failures}, indent=2, ensure_ascii=False))
    if failures:
        print(f"\nINTEGRATION_FAIL: {len(failures)} property violation(s)")
        return 1
    print(f"\nINTEGRATION_OK: {len(rows)} probes, all safety properties held")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
