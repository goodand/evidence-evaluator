"""Thin read-only adapter around the local Obsidian command-line interface."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Callable

from .corpus import CanonicalPath
from .profile import VaultProfile


CommandRunner = Callable[
    [list[str], object, int], subprocess.CompletedProcess[str]
]


@dataclass(frozen=True)
class ObsidianGraphResult:
    outgoing: tuple[str, ...]
    backlinks: tuple[str, ...]
    warnings: tuple[str, ...]
    available: bool
    # (code, path) per failed probe, classified at the source -- see
    # `_classify_probe_failure`. The warning STRING kept collapsing two
    # different worlds ("the CLI is down" vs "this path is not in Obsidian's
    # index") into one message that a zero-context reader misread as a CLI
    # outage while the CLI was healthy
    # (docs/INDEPENDENT_TEST_HAIKU_MCP_20260822.md). Typing the reason here
    # makes that conflation impossible downstream, whatever the wording.
    failures: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ObsidianBacklinksResult:
    """Result of a backlinks-only probe -- see `ObsidianCliBackend.backlinks_only`."""

    backlinks: tuple[str, ...]
    warnings: tuple[str, ...]
    available: bool
    failures: tuple[tuple[str, str], ...] = ()


# Probe-failure classes. CLI_UNAVAILABLE and NOT_INDEXED are DIFFERENT worlds:
# the first means the CLI process did not answer at all, the second means a
# healthy CLI answered "that path is not in my index" (Obsidian does not index
# dot-directories, so e.g. `.vault-harness/...` paths always land here).
PROBE_NOT_INDEXED = "NOT_INDEXED"
PROBE_CLI_UNAVAILABLE = "CLI_UNAVAILABLE"
PROBE_CLI_ERROR = "CLI_ERROR"

_UNAVAILABLE_MARKERS = (
    "unable to find obsidian",
    "connection refused",
    "timed out",
    "timeout",
)


def _classify_probe_failure(returncode: int, output: str, error: str) -> str:
    """ORDER MATTERS. A spawn failure is converted by `_run` to returncode 127
    with the OS error text -- which contains "No such file or directory". A
    text-first match would classify a dead CLI as NOT_INDEXED, inverting the
    misreading this classification exists to prevent. So unavailability is
    decided first, from the returncode and unambiguous markers; only then is
    "not found" read as the CLI answering about its index."""
    text = f"{output}\n{error}".casefold()
    if returncode == 127 or any(marker in text for marker in _UNAVAILABLE_MARKERS):
        return PROBE_CLI_UNAVAILABLE
    if "not found" in text:
        return PROBE_NOT_INDEXED
    return PROBE_CLI_ERROR


def parse_cli_output(output: str) -> Any:
    stripped = output.strip()
    if not stripped or stripped.casefold().startswith("no "):
        return []
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return [line.strip() for line in stripped.splitlines() if line.strip()]


def graph_paths(value: Any) -> list[str]:
    """Normalize known JSON and line-oriented graph output shapes."""
    paths: list[str] = []

    def visit(item: Any) -> None:
        if isinstance(item, str):
            candidate = _normalize_graph_path(item)
            if candidate and candidate not in paths:
                paths.append(candidate)
            return
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if isinstance(item, dict):
            found_path_field = False
            for key in ("file", "path", "source", "target"):
                if isinstance(item.get(key), str):
                    visit(item[key])
                    found_path_field = True
            for key, child in item.items():
                if isinstance(key, str) and key.casefold().endswith(".md"):
                    visit(key)
                    found_path_field = True
                elif not found_path_field and isinstance(child, (list, dict)):
                    visit(child)

    visit(value)
    return paths


class ObsidianCliBackend:
    """Query graph edges; `cwd` is the actual vault-selection boundary."""

    def __init__(
        self,
        profile: VaultProfile,
        *,
        runner: CommandRunner | None = None,
        timeout: int = 15,
    ):
        self.profile = profile
        self.timeout = timeout
        self._runner = runner or _run

    def neighbors(self, path: CanonicalPath) -> ObsidianGraphResult:
        values: dict[str, tuple[str, ...]] = {}
        warnings: list[str] = []
        failures: list[tuple[str, str]] = []
        successes = 0
        for key, subcommand in (("backlinks", "backlinks"), ("outgoing", "links")):
            paths, warning, code = self._probe(path, subcommand, counts=subcommand == "backlinks")
            if warning is not None:
                warnings.append(warning)
                failures.append((code or PROBE_CLI_ERROR, path.relative))
                values[key] = ()
                continue
            successes += 1
            values[key] = paths or ()
        return ObsidianGraphResult(
            outgoing=values.get("outgoing", ()),
            backlinks=values.get("backlinks", ()),
            warnings=tuple(warnings),
            available=successes > 0,
            failures=tuple(failures),
        )

    def backlinks_only(self, path: CanonicalPath) -> ObsidianBacklinksResult:
        """Single-call variant: only `backlinks`, never `links`/`tags` too.

        `neighbors()` always issues two CLI calls (`backlinks` and `links`)
        because a graph walk needs both. A consumer that only ever reads
        backlinks -- e.g. a live-only exact-path diagnostic tool -- pays for
        a `links` call it never uses: one more chance of a transient IPC
        failure for a result that call site discards. This exists so that
        consumer does not have to reimplement the CLI invocation or output
        parsing just to avoid the extra call.
        """
        paths, warning, code = self._probe(path, "backlinks", counts=True)
        return ObsidianBacklinksResult(
            backlinks=paths or (),
            warnings=(warning,) if warning else (),
            available=warning is None,
            failures=((code or PROBE_CLI_ERROR, path.relative),) if warning else (),
        )

    def _probe(
        self, path: CanonicalPath, subcommand: str, *, counts: bool = False
    ) -> tuple[tuple[str, ...] | None, str | None, str | None]:
        """Run one CLI subcommand.

        Returns (paths, warning, failure_code); `None` paths means the warning
        and code are set. The code is one of the PROBE_* constants -- the typed
        reason travels with the human-readable warning so downstream layers
        never have to re-derive the reason from the message text."""
        command = [self.profile.obsidian_binary, subcommand]
        if self.profile.vault_name:
            command.append(f"vault={self.profile.vault_name}")
        command.append(f"path={path.relative}")
        if counts:
            command.extend(("counts", "format=json"))
        result = self._call(command)
        output = result.stdout.strip()
        error = result.stderr.strip()
        if result.returncode != 0 or _looks_like_error(output):
            code = _classify_probe_failure(result.returncode, output, error)
            return None, (
                f"Obsidian {subcommand} unavailable for {path.relative}: "
                f"{error or output or 'command failed'}"
            ), code
        return tuple(graph_paths(parse_cli_output(output))), None, None

    def _call(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        result = self._runner(command, self.profile.root, self.timeout)
        if _transient_app_error(result.stdout, result.stderr):
            time.sleep(0.05)
            result = self._runner(command, self.profile.root, self.timeout)
        return result


def _run(command: list[str], cwd: object, timeout: int) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(command, 127, "", str(exc))


def _normalize_graph_path(raw: str) -> str | None:
    value = raw.split("\t", 1)[0].strip()
    if value.startswith("[[") and value.endswith("]]" ):
        value = value[2:-2].split("|", 1)[0].split("#", 1)[0].strip()
    base = value.split("#", 1)[0]
    if (
        not value
        or value.startswith("#")
        or "://" in value
        or any(character.isspace() for character in value)
        or (
            PurePosixPath(base).suffix
            and PurePosixPath(base).suffix.casefold() != ".md"
        )
    ):
        return None
    return value


def _looks_like_error(output: str) -> bool:
    folded = output.casefold()
    error_prefixes = (
        "error",
        "failed",
        "unable",
        "could not",
        "cannot",
        "connection refused",
    )
    return "unable to find obsidian" in folded or any(
        line.strip().startswith(error_prefixes) for line in folded.splitlines()
    )


def _transient_app_error(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".casefold()
    return "unable to find obsidian" in combined
