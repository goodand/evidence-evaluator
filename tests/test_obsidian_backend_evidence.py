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


class _BackendWithoutBacklinksOnly:
    """An older evidence_evaluator: ObsidianCliBackend with `neighbors()` but
    no `backlinks_only()`. Real, not hypothetical -- reproduced 2026-08-16
    against the actual evidence-evaluator checkout, whose working tree
    predated that method while its branch tip already had it."""

    def neighbors(self, path):
        raise AssertionError("should never be reached")


def test_an_evidence_evaluator_without_backlinks_only_is_unavailable_not_a_crash():
    """Adversarial review 2026-08-16 (blocker): this raised a bare
    AttributeError, which contracts.py does not catch -- it handles only
    ObsidianUnavailable -- so it escaped to the MCP boundary as an unhandled
    exception. A version mismatch is an unavailable backend, not a crash."""
    with pytest.raises(ObsidianUnavailable) as excinfo:
        fetch_backlinks(Path("/vault"), "myvault", "target.md",
                        backend=_BackendWithoutBacklinksOnly())
    assert "backlinks_only" in str(excinfo.value)


def test_evidence_evaluator_dir_expands_a_tilde():
    """A `~`-relative EVIDENCE_EVALUATOR_DIR used to land on sys.path
    literally, where no import can resolve it (adversarial review
    2026-08-16)."""
    import obsidian_backend_evidence as mod
    assert "~" not in str(mod._EVIDENCE_DIR)
