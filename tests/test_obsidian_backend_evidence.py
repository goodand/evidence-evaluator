from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from obsidian_backend_evidence import (ObsidianUnavailable,  # noqa: E402
                                       confirm_active_vault, fetch_backlinks)


@dataclass(frozen=True)
class _FakeBacklinksResult:
    backlinks: tuple[str, ...]
    warnings: tuple[str, ...]
    available: bool


class _FakeBackend:
    """Stands in for `evidence_evaluator.retrieval.obsidian.ObsidianCliBackend`
    without needing evidence-evaluator importable or a real vault present."""

    def __init__(self, result: _FakeBacklinksResult):
        self._result = result
        self.calls: list[str] = []

    def backlinks_only(self, path):
        self.calls.append(path.relative)
        return self._result


def test_fetch_backlinks_returns_shaped_entries():
    backend = _FakeBackend(_FakeBacklinksResult(
        backlinks=("a.md", "b.md"), warnings=(), available=True))
    result = fetch_backlinks(Path("/vault"), "myvault", "target.md", backend=backend)
    assert result == [{"file": "a.md"}, {"file": "b.md"}]
    assert backend.calls == ["target.md"]


def test_fetch_backlinks_raises_when_the_probe_is_unavailable():
    backend = _FakeBackend(_FakeBacklinksResult(
        backlinks=(), warnings=("obsidian backlinks unavailable: boom",), available=False))
    with pytest.raises(ObsidianUnavailable):
        fetch_backlinks(Path("/vault"), "myvault", "target.md", backend=backend)


def test_fetch_backlinks_link_count_is_always_the_fallback_default():
    """Poison test for the measured semantic gap this module's docstring
    names: evidence_evaluator's `graph_paths()` strips per-file link counts,
    so every entry here has no `count` key at all -- `contracts.py`'s own
    `int(item.get("count", 1))` is what turns the ABSENCE into `1`, not this
    module claiming a real count of 1. Assert the absence directly so a
    future fix upstream (a counts-preserving `backlinks_only()`) makes this
    test fail loudly instead of silently drifting."""
    backend = _FakeBackend(_FakeBacklinksResult(
        backlinks=("a.md",), warnings=(), available=True))
    result = fetch_backlinks(Path("/vault"), "myvault", "target.md", backend=backend)
    # Assert the call happened too, not just the shape of what came back.
    # Adversarial review 2026-08-15: asserting only on the returned shape let
    # an implementation that never touched the backend and returned a
    # hardcoded list pass this test unchanged.
    assert backend.calls == ["target.md"], "backlinks_only() was never called"
    assert "count" not in result[0], (
        "evidence_evaluator now preserves counts -- update this module's "
        "docstring, this test, and reconsider whether the measured gap "
        "still blocks making this the default backend"
    )


def test_confirm_active_vault_is_always_unknown():
    """No equivalent cross-check exists in evidence_evaluator yet. Must not
    silently return "confirmed" -- that would violate this server's own
    rule (obsidian_backend.py) never to assume active-vault status without a
    real check."""
    assert confirm_active_vault(Path("/vault")) == "unknown"
