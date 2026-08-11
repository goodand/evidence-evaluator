"""Command-line transport for the canonical vault retrieval service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .profile import ProfileError, VaultProfile
from .retriever import RetrievalError
from .service import RetrievalService, ServiceError


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(prog="evidence-vault", description=__doc__)
    value.add_argument("--profile", type=Path)
    value.add_argument("--root", type=Path)
    value.add_argument("--vault-name")
    value.add_argument("--obsidian-binary", default="/usr/local/bin/obsidian")
    value.add_argument("--no-obsidian", action="store_true")
    subcommands = value.add_subparsers(dest="command", required=True)

    search = subcommands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--output-k", type=int, default=8)
    search.add_argument("--candidate-pool-k", type=int, default=50)
    search.add_argument("--graph-seed-k", type=int, default=12)
    search.add_argument("--max-turns", type=int, default=6)

    read = subcommands.add_parser("read")
    read.add_argument("path")
    read.add_argument("--line-start", type=int, default=1)
    read.add_argument("--line-count", type=int, default=200)

    subcommands.add_parser("policy")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        profile = _profile(args)
        service = RetrievalService.from_profile(profile)
        if args.command == "search":
            result = service.search(
                args.query,
                output_k=args.output_k,
                candidate_pool_k=args.candidate_pool_k,
                graph_seed_k=args.graph_seed_k,
                max_turns=args.max_turns,
            )
        elif args.command == "read":
            result = service.read(
                args.path,
                line_start=args.line_start,
                line_count=args.line_count,
            )
        else:
            result = service.policy()
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    except (OSError, ProfileError, RetrievalError, ServiceError, ValueError) as exc:
        json.dump({"error": str(exc)}, sys.stderr, ensure_ascii=False)
        sys.stderr.write("\n")
        return 2


def _profile(args: argparse.Namespace) -> VaultProfile:
    if args.profile and args.root:
        raise ProfileError("Use --profile or --root, not both")
    if args.profile:
        profile = VaultProfile.from_json(args.profile)
        if args.no_obsidian and profile.obsidian_enabled:
            payload = {
                "root": str(profile.root),
                "vault_name": profile.vault_name,
                "obsidian_binary": profile.obsidian_binary,
                "obsidian_enabled": False,
                "aliases": {key: list(values) for key, values in profile.aliases.items()},
                "authority_prefixes": list(profile.authority_prefixes),
                "excluded_globs": list(profile.excluded_globs),
                "blocked_parts": list(profile.blocked_parts),
                "max_markdown_bytes": profile.max_markdown_bytes,
            }
            return VaultProfile.from_mapping(payload)
        return profile
    if not args.root:
        raise ProfileError("Use --profile or --root")
    return VaultProfile(
        root=args.root,
        vault_name=args.vault_name,
        obsidian_binary=args.obsidian_binary,
        obsidian_enabled=not args.no_obsidian,
    )


if __name__ == "__main__":
    raise SystemExit(main())

