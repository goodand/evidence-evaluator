"""Configuration and path policy for one Markdown vault."""

from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Mapping


DEFAULT_BLOCKED_PARTS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".pytest_cache",
        "__pycache__",
        "hidden_gold",
        "node_modules",
        "private_eval",
    }
)


class ProfileError(ValueError):
    """Raised when a vault profile cannot define a safe runtime."""


@dataclass(frozen=True)
class VaultProfile:
    """Portable runtime configuration with one path-admission policy."""

    root: Path
    vault_name: str | None = None
    obsidian_binary: str = "/usr/local/bin/obsidian"
    obsidian_enabled: bool = True
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    authority_prefixes: tuple[str, ...] = ()
    excluded_globs: tuple[str, ...] = ()
    blocked_parts: frozenset[str] = DEFAULT_BLOCKED_PARTS
    max_markdown_bytes: int = 2_000_000

    def __post_init__(self) -> None:
        root = Path(self.root).expanduser().resolve()
        if not root.is_dir():
            raise ProfileError(f"Vault root is not a directory: {root}")
        if self.max_markdown_bytes < 1:
            raise ProfileError("max_markdown_bytes must be positive")

        normalized_aliases: dict[str, tuple[str, ...]] = {}
        for key, values in self.aliases.items():
            folded = str(key).strip().casefold()
            if not folded:
                raise ProfileError("Alias keys must not be empty")
            normalized_aliases[folded] = tuple(
                dict.fromkeys(str(value).strip() for value in values if str(value).strip())
            )

        object.__setattr__(self, "root", root)
        object.__setattr__(self, "aliases", normalized_aliases)
        object.__setattr__(
            self,
            "authority_prefixes",
            tuple(_normalize_prefix(value) for value in self.authority_prefixes),
        )
        object.__setattr__(
            self,
            "excluded_globs",
            tuple(str(value).strip() for value in self.excluded_globs if str(value).strip()),
        )
        object.__setattr__(
            self,
            "blocked_parts",
            frozenset(str(value).casefold() for value in self.blocked_parts),
        )

    def is_blocked_path(self, value: str | Path) -> bool:
        """Return true for paths that may not enter any retrieval layer."""
        raw = value.as_posix() if isinstance(value, Path) else str(value)
        raw = raw.replace("\\", "/")
        candidate = PurePosixPath(raw)
        if candidate.is_absolute() or any(part in {"", ".."} for part in candidate.parts):
            return True
        folded_parts = tuple(part.casefold() for part in candidate.parts)
        if any(
            part in self.blocked_parts
            or part.startswith(".venv")
            or part.startswith("venv-")
            for part in folded_parts
        ):
            return True
        normalized = candidate.as_posix()
        return any(
            fnmatch.fnmatch(normalized, pattern)
            or candidate.match(pattern)
            for pattern in self.excluded_globs
        )

    def authority_rank(self, relative_path: str) -> tuple[int, str]:
        normalized = PurePosixPath(relative_path).as_posix()
        for rank, prefix in enumerate(self.authority_prefixes):
            if normalized == prefix.rstrip("/") or normalized.startswith(prefix):
                return rank, normalized
        return len(self.authority_prefixes), normalized

    def expand_query(self, query: str) -> list[str]:
        values = [query]
        lowered = query.casefold()
        tokens = set(lowered.replace("/", " ").split())
        for key, expansions in self.aliases.items():
            if key in lowered or key in tokens:
                values.extend(expansions)
        return list(dict.fromkeys(value for value in values if value.strip()))

    @classmethod
    def from_mapping(
        cls,
        payload: Mapping[str, Any],
        *,
        base_dir: Path | None = None,
    ) -> "VaultProfile":
        if "root" not in payload:
            raise ProfileError("Profile requires root")
        root = Path(str(payload["root"])).expanduser()
        if not root.is_absolute() and base_dir is not None:
            root = base_dir / root
        aliases = payload.get("aliases") or {}
        if not isinstance(aliases, Mapping):
            raise ProfileError("aliases must be an object")
        return cls(
            root=root,
            vault_name=_optional_string(payload.get("vault_name")),
            obsidian_binary=str(
                payload.get("obsidian_binary", "/usr/local/bin/obsidian")
            ),
            obsidian_enabled=bool(payload.get("obsidian_enabled", True)),
            aliases={
                str(key): tuple(str(item) for item in values)
                for key, values in aliases.items()
                if isinstance(values, list)
            },
            authority_prefixes=tuple(payload.get("authority_prefixes") or ()),
            excluded_globs=tuple(payload.get("excluded_globs") or ()),
            blocked_parts=frozenset(
                payload.get("blocked_parts") or DEFAULT_BLOCKED_PARTS
            ),
            max_markdown_bytes=int(payload.get("max_markdown_bytes", 2_000_000)),
        )

    @classmethod
    def from_json(cls, path: Path) -> "VaultProfile":
        resolved = path.expanduser().resolve()
        payload = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ProfileError("Profile JSON must contain an object")
        return cls.from_mapping(payload, base_dir=resolved.parent)

    @classmethod
    def from_env(cls) -> "VaultProfile":
        profile_path = os.environ.get("EVIDENCE_VAULT_PROFILE")
        if profile_path:
            return cls.from_json(Path(profile_path))
        root = os.environ.get("EVIDENCE_VAULT_ROOT")
        if not root:
            raise ProfileError(
                "Set EVIDENCE_VAULT_PROFILE or EVIDENCE_VAULT_ROOT"
            )
        return cls(
            root=Path(root),
            vault_name=_optional_string(os.environ.get("EVIDENCE_VAULT_NAME")),
            obsidian_binary=os.environ.get(
                "OBSIDIAN_CLI", "/usr/local/bin/obsidian"
            ),
            obsidian_enabled=os.environ.get("EVIDENCE_OBSIDIAN_ENABLED", "1")
            not in {"0", "false", "False"},
        )


def _normalize_prefix(value: str) -> str:
    prefix = PurePosixPath(str(value).strip().replace("\\", "/")).as_posix()
    if prefix in {"", "."} or prefix.startswith("../"):
        raise ProfileError(f"Invalid authority prefix: {value}")
    return prefix.rstrip("/") + "/"


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
