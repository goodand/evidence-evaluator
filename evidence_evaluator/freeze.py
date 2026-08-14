"""Shared hash receipt verification for private evaluation bundles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_tree_freeze(root: Path, repo: Path) -> dict[str, Any]:
    freeze_path = root / "freeze.json"
    freeze = json.loads(freeze_path.read_text(encoding="utf-8"))
    claimed_digest = freeze.get("freeze_digest")
    unsigned = {key: value for key, value in freeze.items() if key != "freeze_digest"}
    failures: list[str] = []
    if claimed_digest != canonical_digest(unsigned):
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
        if not path.is_file() or sha256_file(path) != digest:
            failures.append(f"asset drift: {relative}")

    for relative, digest in (freeze.get("harness_surface") or {}).items():
        path = repo / relative
        if not path.is_file() or sha256_file(path) != digest:
            failures.append(f"harness drift: {relative}")

    return {
        "contract_version": "handoff-confirmatory-freeze-check-v1",
        "status": "PASS" if not failures else "FAIL",
        "freeze_digest": claimed_digest,
        "failures": failures,
    }
