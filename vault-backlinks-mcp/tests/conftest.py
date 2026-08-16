from __future__ import annotations

import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

import contracts  # noqa: E402


@pytest.fixture(autouse=True)
def _stub_active_vault_confirmation(monkeypatch):
    """Without this, `query_backlinks()` calls the real `confirm_active_vault`,
    which shells out to the actual Obsidian CLI on whatever machine runs the
    suite -- a real environment dependency in what is otherwise a fully
    hermetic, mocked-IPC test suite. That would make every existing test's
    `review_checks` depend on whether Obsidian happens to be running and
    what it's pointed at, which is exactly the kind of non-determinism this
    package's own tests exist to avoid.

    Default to "confirmed" (the common case, and the one that adds no extra
    review_check) so existing tests keep asserting on the checks they were
    written for. Tests for the ACTIVE_VAULT_MISMATCH/ACTIVE_VAULT_UNKNOWN
    paths override this per-test.
    """
    monkeypatch.setattr(contracts, "confirm_active_vault", lambda vault_root: "confirmed")
