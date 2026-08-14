#!/usr/bin/env python3
"""Validate a curator draft and materialize an isolated handoff eval corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath


DIFFICULTIES = {
    "paraphrase",
    "bilingual-alias",
    "multi-hop",
    "dated-collision",
    "same-name",
    "backlink-entry",
}
FORBIDDEN = ("hmc", "boreal relay", "cinder ledger", "handoff-mcp-canary")


def _safe_markdown_path(raw: str) -> str:
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or path.suffix.casefold() != ".md":
        raise ValueError(f"unsafe Markdown path: {raw!r}")
    return path.as_posix()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _extra_collision_documents(case: dict) -> dict[str, str]:
    if case["difficulty"] == "dated-collision":
        base = PurePosixPath(case["handoff_filename"]).parent.as_posix()
        prefix = case["state_code"].split("_", 1)[0]
        return {
            f"{base}/2026-07-18 Handoff.md": (
                "# Juniper Tidal Lab — 2026-07-18 Handoff\n\n"
                "Status: superseded. This obsolete route must not control.\n\n"
                f"STATE_CODE: {prefix}_STALE_UNRESTRICTED\n"
                f"NEXT_ACTION_CODE: {prefix}_START_OVERNIGHT_RUN\n"
                f"STOP_CODE: {prefix}_IGNORE_NEWER_RECORD\n"
            ),
            f"{base}/2026-07-18 Authority.md": (
                "# Juniper Tidal Lab — 2026-07-18 Authority\n\n"
                "Status: superseded by the 2026-08-12 authority.\n\n"
                f"STATE_CODE: {prefix}_STALE_UNRESTRICTED\n"
                f"NEXT_ACTION_CODE: {prefix}_START_OVERNIGHT_RUN\n"
                f"STOP_CODE: {prefix}_IGNORE_NEWER_RECORD\n"
            ),
        }
    if case["difficulty"] == "same-name":
        base = f"Archive/{case['project_label']}"
        prefix = case["state_code"].split("_", 1)[0]
        return {
            f"{base}/Handoff.md": (
                f"# {case['project_label']} Handoff\n\nStatus: archived collision.\n\n"
                f"STATE_CODE: {prefix}_STALE_LAYOUT_OPEN\n"
                f"NEXT_ACTION_CODE: {prefix}_RELOCATE_ITEMS\n"
            ),
            f"{base}/Authority.md": (
                f"# {case['project_label']} Authority\n\nStatus: archived collision.\n\n"
                f"STATE_CODE: {prefix}_STALE_LAYOUT_OPEN\n"
                f"NEXT_ACTION_CODE: {prefix}_RELOCATE_ITEMS\n"
            ),
        }
    return {}


def materialize(draft_path: Path, output: Path) -> dict:
    draft_bytes = draft_path.read_bytes()
    draft = json.loads(draft_bytes)
    cases = draft.get("cases")
    if not isinstance(cases, list) or len(cases) != 6:
        raise ValueError("curator draft must contain exactly six cases")
    if {case.get("difficulty") for case in cases} != DIFFICULTIES:
        raise ValueError("curator draft must contain each required difficulty exactly once")

    encoded = json.dumps(draft, ensure_ascii=False).casefold()
    if any(term in encoded for term in FORBIDDEN):
        raise ValueError("curator draft overlaps a development identifier")

    filenames: set[str] = set()
    codes: set[str] = set()
    for case in cases:
        for key in ("entry_filename", "handoff_filename", "authority_filename"):
            path = _safe_markdown_path(case[key])
            if path in filenames:
                raise ValueError(f"duplicate corpus path: {path}")
            filenames.add(path)
        case_codes = {
            case["state_code"], case["next_action_code"],
            *case["stop_condition_codes"],
        }
        if codes & case_codes:
            raise ValueError("codes must be unique across cases")
        codes.update(case_codes)
        if len(case["stop_condition_codes"]) != 2:
            raise ValueError("each case must contain exactly two stop conditions")
        for key in ("entry_body", "handoff_body", "authority_body"):
            if not 1 <= len(case[key]) <= 1800:
                raise ValueError(f"invalid body length for {case['id']}:{key}")

    if output.exists():
        raise ValueError(f"refusing to overwrite frozen output: {output}")
    corpus = output / "corpus"
    case_dir = output / "cases"
    gold_dir = output / "gold"
    corpus.mkdir(parents=True)

    manifest_cases = []
    for case in cases:
        question = case["question"]
        amendments = []
        if case["difficulty"] == "paraphrase" and case["project_label"] not in question:
            question = f"For {case['project_label']}, {question[0].lower() + question[1:]}"
            amendments.append("added project identifier; retained paraphrased state/action wording")

        documents = {
            case["entry_filename"]: case["entry_body"],
            case["handoff_filename"]: case["handoff_body"],
            case["authority_filename"]: case["authority_body"],
            **_extra_collision_documents(case),
        }
        if len(documents) > 3:
            amendments.append("materialized the collision as physical distractor files")
        for relative, body in documents.items():
            destination = corpus / _safe_markdown_path(relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(body.rstrip() + "\n", encoding="utf-8")

        public_case = {
            "contract_version": "handoff-mcp-canary-case-v1",
            "id": f"CONF-{case['id'].split('-')[-1]}",
            "project_id": case["project_label"],
            "question": question,
        }
        gold = {
            "contract_version": "handoff-mcp-canary-gold-v1",
            "case_id": public_case["id"],
            "handoff_path": case["handoff_filename"],
            "authority_paths": [case["authority_filename"]],
            "navigation_paths": [case["entry_filename"]],
            "required_read_paths": [case["handoff_filename"], case["authority_filename"]],
            "state_code": case["state_code"],
            "next_action_code": case["next_action_code"],
            "stop_condition_codes": case["stop_condition_codes"],
        }
        _write_json(case_dir / f"{public_case['id']}.json", public_case)
        _write_json(gold_dir / f"{public_case['id']}.json", gold)
        manifest_cases.append({
            "id": public_case["id"],
            "difficulty": case["difficulty"],
            "case_file": f"cases/{public_case['id']}.json",
            "gold_file": f"gold/{public_case['id']}.json",
            "documents": sorted(documents),
            "amendments": amendments,
        })

    profile = {
        "root": str(corpus.resolve()),
        "vault_name": "handoff-confirmatory-v1",
        "obsidian_enabled": False,
        "authority_prefixes": ["Projects"],
    }
    _write_json(output / "profile.json", profile)
    shutil.copyfile(draft_path, output / "curator-draft.json")
    manifest = {
        "contract_version": "handoff-confirmatory-manifest-v1",
        "set_id": "handoff-confirmatory-v1",
        "status": "frozen-unrun",
        "curator_draft_sha256": hashlib.sha256(draft_bytes).hexdigest(),
        "cases": manifest_cases,
        "limitations": [
            "synthetic isolated corpus",
            "curator and main agent are different model sessions, not different organizations",
            "cases were structurally audited but have not been used for harness repair",
        ],
    }
    _write_json(output / "manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(materialize(args.draft, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
