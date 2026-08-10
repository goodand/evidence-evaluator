from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent / "vault_backlinks_mcp"
sys.path.insert(0, str(PKG))

import pytest  # noqa: E402

from obsidian_backend import (ObsidianUnavailable, confirm_active_vault,  # noqa: E402
                              fetch_backlinks)


# --- regressions from the 2026-08-09 independent review of the
# .vault-harness reuse contract, finding #4 --------------------------------
# fetch_backlinks() used to call the shared graph_for_candidate(), which
# always issues three Obsidian CLI calls (backlinks, links, tags) even
# though only backlinks is ever used here -- three times the exposure to an
# IPC channel already measured as unreliable, for one-third the useful data.

def test_fetch_backlinks_issues_exactly_one_cli_call(tmp_path):
    calls = []

    def fake_run(command, cwd, timeout=15):
        calls.append((command, cwd))
        return subprocess.CompletedProcess(command, 0, '[{"file": "a.md", "count": "1"}]', "")

    result = fetch_backlinks(tmp_path, "myvault", "target.md", run_fn=fake_run)

    assert len(calls) == 1, f"expected exactly 1 CLI call, got {len(calls)}: {calls}"
    command, cwd = calls[0]
    assert command[1] == "backlinks"
    assert "links" not in command and "tags" not in command
    assert cwd == tmp_path
    assert result == [{"file": "a.md", "count": "1"}]


def test_fetch_backlinks_retries_once_on_transient_ipc_failure(tmp_path):
    attempts = []

    def flaky_then_ok(command, cwd, timeout=15):
        attempts.append(1)
        if len(attempts) == 1:
            return subprocess.CompletedProcess(command, 1, "unable to find Obsidian", "")
        return subprocess.CompletedProcess(command, 0, "[]", "")

    result = fetch_backlinks(tmp_path, "myvault", "target.md", run_fn=flaky_then_ok)
    assert len(attempts) == 2
    assert result == []


def test_fetch_backlinks_raises_after_two_failures(tmp_path):
    def always_fails(command, cwd, timeout=15):
        return subprocess.CompletedProcess(command, 1, "", "boom")

    with pytest.raises(ObsidianUnavailable, match="boom"):
        fetch_backlinks(tmp_path, "myvault", "target.md", run_fn=always_fails)


def test_fetch_backlinks_rejects_non_list_output(tmp_path):
    def bad_shape(command, cwd, timeout=15):
        return subprocess.CompletedProcess(command, 0, '{"not": "a list"}', "")

    with pytest.raises(ObsidianUnavailable, match="not a list"):
        fetch_backlinks(tmp_path, "myvault", "target.md", run_fn=bad_shape)


# --- regression from finding #2 (independent review, 2026-08-09) ----------
# The harness directory was a hardcoded Path.home()/"Desktop"/"Project_in_
# progress"/... that only worked on the one machine, user, and layout this
# server was first written under. VAULT_HARNESS_DIR must override it. This
# has to run in a subprocess: _HARNESS_DIR is computed once at import time.

def test_vault_harness_dir_env_var_overrides_the_hardcoded_default(tmp_path):
    env = dict(os.environ)
    env["VAULT_HARNESS_DIR"] = str(tmp_path / "somewhere-else")
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'vault_backlinks_mcp'); "
         "import obsidian_backend; print(obsidian_backend._HARNESS_DIR)"],
        cwd=str(PKG.parent), env=env, capture_output=True, text=True)
    assert proc.stdout.strip() == str(tmp_path / "somewhere-else")


# --- confirm_active_vault (added 2026-08-10 in response to independent
# review round 2, finding #3): a second, independent CLI subcommand cross-
# check, contributed by the .vault-harness reuse-contract review session
# after confirming `obsidian vault info=path` follows `cwd` the same way
# `backlinks` does (i.e. not a true GUI-focus oracle, but still a real
# disagreement-detector). Its own explicit guidance: never guess "confirmed"
# on CLI failure.

def test_confirm_active_vault_matches_reports_confirmed(tmp_path):
    def fake_run(command, cwd, timeout=15):
        return subprocess.CompletedProcess(command, 0, str(tmp_path), "")
    assert confirm_active_vault(tmp_path, run_fn=fake_run) == "confirmed"


def test_confirm_active_vault_mismatch_reports_mismatch(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    def fake_run(command, cwd, timeout=15):
        return subprocess.CompletedProcess(command, 0, str(other), "")
    assert confirm_active_vault(tmp_path, run_fn=fake_run) == "mismatch"


def test_confirm_active_vault_cli_failure_reports_unknown_not_confirmed(tmp_path):
    def fake_run(command, cwd, timeout=15):
        return subprocess.CompletedProcess(command, 1, "", "The CLI is unable to find Obsidian")
    assert confirm_active_vault(tmp_path, run_fn=fake_run) == "unknown"


def test_confirm_active_vault_runner_exception_reports_unknown(tmp_path):
    def raising_run(command, cwd, timeout=15):
        raise OSError("no such file or directory: obsidian")
    assert confirm_active_vault(tmp_path, run_fn=raising_run) == "unknown"
