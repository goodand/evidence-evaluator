#!/usr/bin/env python3
"""Live comparison: `obsidian_backend` (harness) vs `obsidian_backend_evidence`
(evidence_evaluator) against real, representative vault paths.

DESIGN_OBSIDIAN_RETRIEVAL_CANONICAL.md section 8, condition 5 requires this
before the harness can be retired: "Representative live-vault queries are
compared against the old harness and material recall regressions are
recorded rather than hidden." This is that comparison, run against the real
registered vault(s) on this machine -- not a synthetic fixture.

Not part of `tests/`: this package's own test suite is deliberately hermetic
(see `conftest.py`'s module docstring) -- every existing test stubs the CLI.
This script is the opposite on purpose: it needs the real Obsidian CLI and a
real vault, so it stays a manually-run script, not something CI or a default
`pytest` run picks up.

Usage: python3 scripts/parity_check_backends.py [vault_id ...]
Defaults to every vault_id in the configured registry.
"""
from __future__ import annotations

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

from registry import load_registry  # noqa: E402
import obsidian_backend  # noqa: E402
import obsidian_backend_evidence  # noqa: E402


def representative_paths(root: Path, limit: int = 5) -> list[str]:
    """A handful of real Markdown paths under this vault root -- not every
    file, just enough to exercise both backends against real CLI answers."""
    paths = []
    for candidate in sorted(root.rglob("*.md")):
        if any(part.startswith(".") for part in candidate.relative_to(root).parts):
            continue
        paths.append(str(candidate.relative_to(root)))
        if len(paths) >= limit:
            break
    return paths


def compare_one(vault_id: str, root: Path, obsidian_vault_name: str, path: str) -> dict:
    row = {"vault_id": vault_id, "path": path}
    try:
        harness = obsidian_backend.fetch_backlinks(root, obsidian_vault_name, path)
        row["harness_files"] = sorted(item.get("file") for item in harness
                                      if isinstance(item, dict))
        row["harness_error"] = None
    except obsidian_backend.ObsidianUnavailable as exc:
        row["harness_files"] = None
        row["harness_error"] = str(exc)
    try:
        evidence = obsidian_backend_evidence.fetch_backlinks(root, obsidian_vault_name, path)
        row["evidence_files"] = sorted(item.get("file") for item in evidence)
        row["evidence_error"] = None
    except obsidian_backend_evidence.ObsidianUnavailable as exc:
        row["evidence_files"] = None
        row["evidence_error"] = str(exc)
    row["file_sets_match"] = (
        row["harness_files"] is not None
        and row["harness_files"] == row["evidence_files"]
    )
    return row


def main() -> int:
    registry = load_registry()
    vault_ids = sys.argv[1:] or sorted(registry)
    exit_code = 0
    for vault_id in vault_ids:
        if vault_id not in registry:
            print(f"skip {vault_id!r}: not in registry")
            exit_code = 1
            continue
        vault = registry[vault_id]
        for path in representative_paths(vault.root):
            row = compare_one(vault_id, vault.root, vault.obsidian_vault_name, path)
            status = "MATCH" if row["file_sets_match"] else "DIFFER"
            print(f"[{status}] {vault_id}:{path}")
            print(f"  harness : {row['harness_files']!r} err={row['harness_error']!r}")
            print(f"  evidence: {row['evidence_files']!r} err={row['evidence_error']!r}")
            if status == "DIFFER":
                exit_code = 1
    print()
    print("Known, accepted-so-far difference NOT checked above: link counts.")
    print("evidence backend never reports a real count (see")
    print("obsidian_backend_evidence.py's module docstring) -- this script")
    print("only compares WHICH files are returned, not their counts.")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
