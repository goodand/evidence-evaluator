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
        successes = 0
        for key, subcommand in (("backlinks", "backlinks"), ("outgoing", "links")):
            command = [self.profile.obsidian_binary, subcommand]
            if self.profile.vault_name:
                command.append(f"vault={self.profile.vault_name}")
            command.append(f"path={path.relative}")
            if subcommand == "backlinks":
                command.extend(("counts", "format=json"))
            result = self._call(command)
            output = result.stdout.strip()
            error = result.stderr.strip()
            if result.returncode != 0 or _looks_like_error(output):
                warnings.append(
                    f"Obsidian {subcommand} unavailable for {path.relative}: "
                    f"{error or output or 'command failed'}"
                )
                values[key] = ()
                continue
            successes += 1
            values[key] = tuple(graph_paths(parse_cli_output(output)))
        return ObsidianGraphResult(
            outgoing=values.get("outgoing", ()),
            backlinks=values.get("backlinks", ()),
            warnings=tuple(warnings),
            available=successes > 0,
        )

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
