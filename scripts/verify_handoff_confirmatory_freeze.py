#!/usr/bin/env python3
"""Fail closed when a frozen handoff evaluation set or harness surface drifts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from evidence_evaluator.freeze import verify_tree_freeze

# Backward-compatible function name used by callers and existing tests. The
# implementation is shared so CLI and package consumers cannot drift.
verify = verify_tree_freeze


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    result = verify_tree_freeze(args.root.resolve(), repo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
