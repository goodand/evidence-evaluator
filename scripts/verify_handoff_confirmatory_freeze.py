#!/usr/bin/env python3
"""Fail closed when a frozen handoff evaluation set or harness surface drifts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root: Path, repo: Path) -> dict:
    freeze_path = root / "freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    claimed_digest = freeze.get("freeze_digest")
    unsigned = {key: value for key, value in freeze.items() if key != "freeze_digest"}
    actual_digest = hashlib.sha256(
        json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode()
    ).hexdigest()
    failures = []
    if claimed_digest != actual_digest:
        failures.append("freeze receipt digest mismatch")

    expected_assets = freeze.get("assets") or {}
    actual_assets = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "freeze.json"
    }
    if actual_assets != set(expected_assets):
        failures.append("frozen asset path set changed")
    for relative, digest in expected_assets.items():
        path = root / relative
        if not path.is_file() or _sha(path) != digest:
            failures.append(f"asset drift: {relative}")

    for relative, digest in (freeze.get("harness_surface") or {}).items():
        path = repo / relative
        if not path.is_file() or _sha(path) != digest:
            failures.append(f"harness drift: {relative}")

    return {
        "contract_version": "handoff-confirmatory-freeze-check-v1",
        "status": "PASS" if not failures else "FAIL",
        "freeze_digest": claimed_digest,
        "failures": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    result = verify(args.root.resolve(), repo)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
