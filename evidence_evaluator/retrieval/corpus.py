"""Safe Markdown inventory, canonical identity, lexical ranking, and graph."""

from __future__ import annotations

import hashlib
import math
import os
import posixpath
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from .profile import VaultProfile


TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*|[\uac00-\ud7a3]{2,}")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
FILE_MENTION = re.compile(r"`([^`\s]+\.md)`", re.IGNORECASE)


class CorpusError(ValueError):
    """Raised when a corpus path or document violates the read boundary."""


@dataclass(frozen=True, order=True)
class CanonicalPath:
    """A verified, non-symlink, vault-relative Markdown identity."""

    relative: str

    def __post_init__(self) -> None:
        candidate = PurePosixPath(self.relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise CorpusError(f"Canonical path must be vault-relative: {self.relative}")
        if candidate.suffix.casefold() != ".md":
            raise CorpusError(f"Canonical path must be Markdown: {self.relative}")
        object.__setattr__(self, "relative", candidate.as_posix())

    def __str__(self) -> str:
        return self.relative


@dataclass(frozen=True)
class VaultDocument:
    canonical_path: CanonicalPath
    replica_paths: tuple[str, ...]
    title: str
    body: str
    sha256: str


@dataclass(frozen=True)
class ReadResult:
    path: str
    canonical_path: str
    line_start: int
    line_end: int
    total_lines: int
    truncated: bool
    document_sha256: str
    content_sha256: str
    content: str


@dataclass(frozen=True)
class _PhysicalDocument:
    relative: str
    absolute: Path
    body: str
    digest: str


def query_tokens(value: str) -> list[str]:
    return list(dict.fromkeys(item.casefold() for item in TOKEN.findall(value)))


class VaultCorpus:
    """In-memory, read-only corpus suitable for live and experiment use."""

    def __init__(self, profile: VaultProfile):
        self.profile = profile
        self.warnings: list[str] = []
        self.documents: dict[str, VaultDocument] = {}
        self._alias_to_canonical: dict[str, str] = {}
        self._outgoing: dict[str, tuple[str, ...]] = {}
        self._backlinks: dict[str, tuple[str, ...]] = {}
        self._tokens: dict[str, list[str]] = {}
        self._df: Counter[str] = Counter()
        self._inventory()
        self._build_graph()
        for path, document in self.documents.items():
            tokens = query_tokens(document.body)
            self._tokens[path] = tokens
            self._df.update(set(tokens))

    @property
    def root(self) -> Path:
        return self.profile.root

    @property
    def docs(self) -> dict[str, str]:
        """Compatibility view used by `evidence_evaluator.runner`."""
        return {path: document.body for path, document in self.documents.items()}

    def _inventory(self) -> None:
        physical: list[_PhysicalDocument] = []
        symlink_aliases: list[tuple[str, Path]] = []

        for directory, dirnames, filenames in os.walk(self.root, followlinks=False):
            directory_path = Path(directory)
            relative_directory = directory_path.relative_to(self.root)
            kept_directories: list[str] = []
            for name in sorted(dirnames):
                relative = (relative_directory / name).as_posix()
                child = directory_path / name
                if self.profile.is_blocked_path(relative):
                    continue
                if child.is_symlink():
                    self.warnings.append(f"Ignored symlink directory: {relative}")
                    continue
                kept_directories.append(name)
            dirnames[:] = kept_directories

            for name in sorted(filenames):
                path = directory_path / name
                if path.suffix.casefold() != ".md":
                    continue
                relative = path.relative_to(self.root).as_posix()
                if self.profile.is_blocked_path(relative):
                    continue
                if _has_symlink_component(self.root, path):
                    try:
                        target = path.resolve(strict=True)
                        target_relative = target.relative_to(self.root).as_posix()
                    except (OSError, ValueError):
                        self.warnings.append(
                            f"Ignored out-of-root symlink: {relative}"
                        )
                        continue
                    if (
                        target.suffix.casefold() == ".md"
                        and not self.profile.is_blocked_path(target_relative)
                        and not _has_symlink_component(self.root, target)
                    ):
                        symlink_aliases.append((relative, target))
                    continue
                if not path.is_file():
                    continue
                size = path.stat().st_size
                if size > self.profile.max_markdown_bytes:
                    self.warnings.append(f"Ignored oversized Markdown: {relative}")
                    continue
                raw = path.read_bytes()
                try:
                    body = raw.decode("utf-8")
                except UnicodeDecodeError:
                    self.warnings.append(f"Ignored non-UTF-8 Markdown: {relative}")
                    continue
                physical.append(
                    _PhysicalDocument(
                        relative=relative,
                        absolute=path.resolve(),
                        body=body,
                        digest=hashlib.sha256(raw).hexdigest(),
                    )
                )

        by_digest: dict[str, list[_PhysicalDocument]] = defaultdict(list)
        by_absolute: dict[Path, _PhysicalDocument] = {}
        for item in physical:
            by_digest[item.digest].append(item)
            by_absolute[item.absolute] = item

        symlinks_by_digest: dict[str, list[str]] = defaultdict(list)
        for alias, target in symlink_aliases:
            item = by_absolute.get(target)
            if item is not None:
                symlinks_by_digest[item.digest].append(alias)

        for digest, replicas in sorted(by_digest.items()):
            canonical = min(
                replicas,
                key=lambda item: self.profile.authority_rank(item.relative),
            )
            all_paths = sorted(
                {item.relative for item in replicas}
                | set(symlinks_by_digest.get(digest, ()))
            )
            replica_paths = tuple(path for path in all_paths if path != canonical.relative)
            document = VaultDocument(
                canonical_path=CanonicalPath(canonical.relative),
                replica_paths=replica_paths,
                title=_title(canonical.body, canonical.relative),
                body=canonical.body,
                sha256=digest,
            )
            self.documents[canonical.relative] = document
            for path in all_paths:
                self._alias_to_canonical[path] = canonical.relative

    def _build_graph(self) -> None:
        backlinks: dict[str, list[str]] = defaultdict(list)
        for path, document in self.documents.items():
            targets: list[str] = []
            raw_links = (
                MARKDOWN_LINK.findall(document.body)
                + WIKILINK.findall(document.body)
                + FILE_MENTION.findall(document.body)
            )
            for raw in raw_links:
                target = self.resolve_graph_target(raw, source=CanonicalPath(path))
                if target is not None and target.relative not in targets:
                    targets.append(target.relative)
                    backlinks[target.relative].append(path)
            self._outgoing[path] = tuple(targets)
        self._backlinks = {
            path: tuple(dict.fromkeys(backlinks.get(path, ())))
            for path in self.documents
        }

    def canonicalize(self, relative_path: str) -> CanonicalPath | None:
        normalized = _safe_relative(relative_path)
        if normalized is None or self.profile.is_blocked_path(normalized):
            return None
        canonical = self._alias_to_canonical.get(normalized)
        return CanonicalPath(canonical) if canonical else None

    def resolve_graph_target(
        self,
        raw: str,
        *,
        source: CanonicalPath,
    ) -> CanonicalPath | None:
        value = str(raw).split("\t", 1)[0].strip()
        if value.startswith("<") and ">" in value:
            value = value[1 : value.index(">")]
        elif not value.startswith("[["):
            # Markdown permits an optional quoted title after a destination.
            # The title is not part of the graph target.
            value = value.split(maxsplit=1)[0] if value else value
        value = unquote(value)
        if value.startswith("[[") and value.endswith("]]" ):
            value = value[2:-2].split("|", 1)[0].split("#", 1)[0]
        value = value.split("#", 1)[0].split("?", 1)[0].strip()
        if not value or value.startswith(("http://", "https://", "mailto:")):
            return None
        if not PurePosixPath(value).suffix:
            value += ".md"
        candidates = (
            posixpath.normpath(
                posixpath.join(PurePosixPath(source.relative).parent.as_posix(), value)
            ),
            posixpath.normpath(value),
        )
        for candidate in candidates:
            canonical = self.canonicalize(candidate)
            if canonical is not None:
                return canonical

        basename = PurePosixPath(value).name.casefold()
        matches = {
            canonical
            for alias, canonical in self._alias_to_canonical.items()
            if PurePosixPath(alias).name.casefold() == basename
        }
        if len(matches) == 1:
            return CanonicalPath(matches.pop())
        return None

    def exact_rank(self, queries: list[str], limit: int) -> list[tuple[str, float]]:
        ranked: list[tuple[str, float]] = []
        original = queries[0].casefold()
        terms = query_tokens(" ".join(queries))
        for path, document in self.documents.items():
            locator = " ".join((path, document.title, *document.replica_paths)).casefold()
            body = document.body.casefold()
            score = 0.0
            if original in locator:
                score += 200.0
            elif original in body:
                score += 40.0
            score += 30.0 * sum(term in locator for term in terms)
            score += 2.0 * sum(min(3, body.count(term)) for term in terms)
            if score:
                ranked.append((path, score))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:limit]

    def bm25_rank(self, queries: list[str], limit: int) -> list[tuple[str, float]]:
        terms = query_tokens(" ".join(queries))
        if not terms or not self.documents:
            return []
        average_length = sum(len(tokens) for tokens in self._tokens.values()) / max(
            1, len(self._tokens)
        )
        ranked: list[tuple[str, float]] = []
        for path, tokens in self._tokens.items():
            frequencies = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for term in terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                document_frequency = self._df[term]
                inverse = math.log(
                    1
                    + (len(self.documents) - document_frequency + 0.5)
                    / (document_frequency + 0.5)
                )
                denominator = frequency + 1.5 * (
                    0.25 + 0.75 * length / max(1.0, average_length)
                )
                score += inverse * frequency * 2.5 / denominator
            if score:
                ranked.append((path, score))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:limit]

    def lexical_rank(self, query: str, limit: int) -> list[str]:
        queries = self.profile.expand_query(query)
        exact = self.exact_rank(queries, limit)
        bm25 = self.bm25_rank(queries, limit)
        combined: dict[str, float] = defaultdict(float)
        for values in (exact, bm25):
            for rank, (path, _) in enumerate(values, start=1):
                combined[path] += 1.0 / (60 + rank)
        return [
            path
            for path, _ in sorted(combined.items(), key=lambda item: (-item[1], item[0]))[
                :limit
            ]
        ]

    def search(self, query: str, k: int = 4) -> list[str]:
        return self.lexical_rank(query, k)

    def links(self, path: str) -> list[str]:
        canonical = self.canonicalize(path)
        return list(self._outgoing.get(canonical.relative, ())) if canonical else []

    def backlinks(self, path: str) -> list[str]:
        canonical = self.canonicalize(path)
        return list(self._backlinks.get(canonical.relative, ())) if canonical else []

    def read(self, path: str, start: int = 1, end: int = 10**6) -> str:
        if start < 1 or end < start:
            raise CorpusError("Invalid read range")
        result = self.read_range(path, start, min(end - start + 1, 100_000))
        return result.content

    def read_range(self, path: str, line_start: int = 1, line_count: int = 200) -> ReadResult:
        if line_start < 1 or line_count < 1:
            raise CorpusError("line_start and line_count must be positive")
        normalized = _safe_relative(path)
        if normalized is None or self.profile.is_blocked_path(normalized):
            raise CorpusError(f"Unsafe Markdown path: {path}")
        absolute = self.root / normalized
        if _has_symlink_component(self.root, absolute):
            raise CorpusError("Read symlink replicas through their canonical path")
        canonical = self.canonicalize(normalized)
        if canonical is None:
            raise CorpusError(f"Markdown path is not in the corpus: {path}")
        document = self.documents[canonical.relative]
        lines = document.body.splitlines()
        start_index = min(line_start - 1, len(lines))
        end_index = min(len(lines), start_index + line_count)
        content = "\n".join(lines[start_index:end_index])
        return ReadResult(
            path=normalized,
            canonical_path=canonical.relative,
            line_start=start_index + 1,
            line_end=max(start_index + 1, end_index),
            total_lines=len(lines),
            truncated=start_index > 0 or end_index < len(lines),
            document_sha256=document.sha256,
            content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            content=content,
        )


def _safe_relative(value: str) -> str | None:
    raw = str(value).replace("\\", "/")
    candidate = PurePosixPath(raw)
    if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
        return None
    normalized = posixpath.normpath(candidate.as_posix())
    if normalized in {"", "."} or normalized.startswith("../"):
        return None
    if PurePosixPath(normalized).suffix.casefold() != ".md":
        return None
    return normalized


def _has_symlink_component(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _title(body: str, relative_path: str) -> str:
    match = HEADING.search(body)
    return match.group(1).strip() if match else PurePosixPath(relative_path).stem
