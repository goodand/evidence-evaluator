"""Portable, read-only Markdown and Obsidian retrieval."""

from .corpus import CanonicalPath, VaultCorpus
from .profile import VaultProfile
from .service import RetrievalService

__all__ = ["CanonicalPath", "RetrievalService", "VaultCorpus", "VaultProfile"]

