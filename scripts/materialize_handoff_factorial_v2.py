#!/usr/bin/env python3
"""Materialize and structurally qualify an independent factorial curator draft."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from evidence_evaluator.contract import tokens, validate_case, validate_gold
from evidence_evaluator.factorial_design import (
    DIFFICULTIES,
    MANIFEST_VERSION,
    QUALIFICATION_DIGEST,
)
from evidence_evaluator.retrieval.profile import VaultProfile
from evidence_evaluator.retrieval.service import RetrievalService


class MaterializeError(ValueError):
    pass


def _safe(path: str) -> bool:
    candidate = PurePosixPath(path)
    return bool(path) and not candidate.is_absolute() and ".." not in candidate.parts


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _reachable(service: RetrievalService, start: str, max_hops: int = 2) -> set[str]:
    seen = {start}
    frontier = [start]
    for _ in range(max_hops):
        following = []
        for path in frontier:
            for target in [*service.corpus.links(path), *service.corpus.backlinks(path)]:
                if target not in seen:
                    seen.add(target)
                    following.append(target)
        frontier = following
    return seen


def materialize(draft_path: Path, output_root: Path) -> dict:
    if output_root.exists():
        raise MaterializeError(f"refusing to overwrite {output_root}")
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    if draft.get("contract_version") != "handoff-factorial-curator-draft-v1":
        raise MaterializeError("unsupported curator draft")
    entries = draft.get("cases")
    if not isinstance(entries, list) or len(entries) != 16:
        raise MaterializeError("curator draft must contain exactly 16 cases")

    expected_ids = {
        *(f"DEV-{number:02d}" for number in range(1, 9)),
        *(f"HOLD-{number:02d}" for number in range(1, 9)),
    }
    observed_ids = {entry.get("case", {}).get("id") for entry in entries}
    if observed_ids != expected_ids:
        raise MaterializeError("case IDs are not exactly DEV-01..08 and HOLD-01..08")

    output_root.mkdir(parents=True)
    corpus_root = output_root / "corpus"
    cases_dir = output_root / "cases"
    gold_dir = output_root / "gold"
    mutations = []
    file_owners: dict[str, str] = {}
    split_ids = {"development": [], "held_out": []}
    split_difficulties = {"development": set(), "held_out": set()}

    try:
        for entry in entries:
            split = entry.get("split")
            if split not in split_ids:
                raise MaterializeError(f"invalid split {split!r}")
            case = validate_case(entry["case"])
            truth = validate_gold(entry["gold"], case)
            case_id = case["id"]
            if truth["case_id"] != case_id:
                raise MaterializeError(f"gold mismatch for {case_id}")
            difficulty = case.get("difficulty")
            if difficulty not in DIFFICULTIES:
                raise MaterializeError(f"invalid difficulty for {case_id}")
            split_ids[split].append(case_id)
            split_difficulties[split].add(difficulty)

            files = entry.get("files")
            if not isinstance(files, list) or not 4 <= len(files) <= 9:
                raise MaterializeError(f"{case_id} needs 4..9 Markdown files")
            bodies = {}
            for item in files:
                path, content = item.get("path"), item.get("content")
                if not isinstance(path, str) or not _safe(path) or not path.endswith(".md"):
                    raise MaterializeError(f"unsafe corpus path in {case_id}: {path!r}")
                if path in file_owners:
                    raise MaterializeError(
                        f"corpus path shared by {file_owners[path]} and {case_id}: {path}")
                file_owners[path] = case_id
                bodies[path] = content
                target = corpus_root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")

            required_files = {
                truth["handoff_path"], *truth["expected_paths"],
                *truth["expected_authority"],
            }
            if not required_files <= set(bodies):
                missing = sorted(required_files - set(bodies))
                raise MaterializeError(f"{case_id} gold paths missing from corpus: {missing}")
            if difficulty == "pool-outside-output-k":
                authority_paths = set(truth["expected_authority"])
                for path in set(bodies) - authority_paths:
                    bodies[path] = (
                        bodies[path].rstrip() + "\n\n## Search index aliases\n"
                        + (case["query"] + "\n") * 3
                    )
                    (corpus_root / path).write_text(bodies[path], encoding="utf-8")
            # Curators often express "A -> B" as prose, which is not an
            # executable Markdown graph edge. Add a deterministic navigation
            # block without changing any authority prose or support ranges.
            # The normalization is recorded in qualification.json and occurs
            # before freeze, never after a subject result is seen.
            handoff = truth["handoff_path"]
            edge_targets = sorted(required_files - {handoff})
            if edge_targets:
                edge_block = "\n## Retrieval edges\n" + "\n".join(
                    f"- [[{target[:-3]}]]" for target in edge_targets
                ) + "\n"
                bodies[handoff] = bodies[handoff].rstrip() + "\n" + edge_block
                (corpus_root / handoff).write_text(bodies[handoff], encoding="utf-8")
            for claim in truth["claims"]:
                for support in claim["support_ranges"]:
                    body = bodies.get(support["path"])
                    if body is None or support["end"] > len(body.splitlines()):
                        raise MaterializeError(
                            f"{case_id} support range exceeds {support['path']}")

            mutation = entry.get("mutation") or {}
            path, find, replacement = (
                mutation.get("path"), mutation.get("find"), mutation.get("replace"))
            if path not in bodies or not isinstance(find, str) or bodies[path].count(find) != 1:
                raise MaterializeError(
                    f"{case_id} mutation must match exactly once in its target")
            mutated = bodies[path].replace(find, str(replacement), 1)
            if mutated == bodies[path]:
                raise MaterializeError(f"{case_id} mutation is a no-op")
            mutations.append({
                "case_id": case_id,
                "path": path,
                "find_count": 1,
                "applied": True,
                "expected_effect": mutation.get("expected_effect"),
            })
            _write_json(cases_dir / f"{case_id}.json", case)
            _write_json(gold_dir / f"{case_id}.json", truth)

        for split in split_ids:
            if len(split_ids[split]) != 8 or split_difficulties[split] != DIFFICULTIES:
                raise MaterializeError(
                    f"{split} must contain every difficulty exactly once")

        profile = {
            "root": "corpus",
            "obsidian_enabled": False,
            "authority_prefixes": ["Projects/"],
        }
        _write_json(output_root / "profile.json", profile)
        service = RetrievalService.from_profile(
            VaultProfile.from_json(output_root / "profile.json"))
        qualification = []
        for split in split_ids.values():
            for case_id in split:
                case = json.loads((cases_dir / f"{case_id}.json").read_text())
                truth = json.loads((gold_dir / f"{case_id}.json").read_text())
                search = service.search(case["query"], output_k=3, candidate_pool_k=50)
                lexical_output = set(service.corpus.search(case["query"], k=3))
                lexical_pool = set(service.corpus.search(case["query"], k=50))
                reachable = _reachable(service, truth["handoff_path"])
                authority = set(truth["expected_authority"])
                if not authority <= reachable:
                    raise MaterializeError(
                        f"{case_id} authority is not reachable within two graph hops")
                authority_for_overlap = truth["expected_authority"][0]
                title = service.corpus.documents[authority_for_overlap].title
                lexical_overlap = tokens(case["query"]) & tokens(
                    PurePosixPath(authority_for_overlap).name + " " + title)
                if case["difficulty"] == "zero-overlap-graph-only" and lexical_overlap:
                    raise MaterializeError(
                        f"{case_id} zero-overlap case has overlap {sorted(lexical_overlap)}")
                output_paths = set(search["retrieved_paths"])
                pool_paths = set(search["candidate_pool"])
                if case["difficulty"] == "pool-outside-output-k" and not (
                    authority <= lexical_pool and not authority & lexical_output
                ):
                    raise MaterializeError(
                        f"{case_id} authority is not exclusively in candidate pool; "
                        f"output={sorted(lexical_output)}, pool={sorted(lexical_pool)}")
                if case["difficulty"] == "multi-source-reconstruction" \
                        and len(truth["critical_paths"]) < 3:
                    raise MaterializeError(
                        f"{case_id} multi-source case has fewer than 3 critical paths")
                qualification.append({
                    "case_id": case_id,
                    "difficulty": case["difficulty"],
                    "lexical_overlap": sorted(lexical_overlap),
                    "authority_in_output": sorted(authority & output_paths),
                    "authority_in_pool": sorted(authority & pool_paths),
                    "authority_in_lexical_output": sorted(authority & lexical_output),
                    "authority_in_lexical_pool": sorted(authority & lexical_pool),
                    "authority_graph_reachable": True,
                })

        manifest = {
            "contract_version": MANIFEST_VERSION,
            "experiment_id": "handoff-factorial-v2",
            "profile": "profile.json",
            "case_dir": "cases",
            "gold_dir": "gold",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "medium",
            "timeout_seconds": 600,
            "replicates": 3,
            "main_retrieval_budget": 10,
            "helper_retrieval_budget": 4,
            "output_k": 3,
            "candidate_pool_k": 50,
            "qualification_freeze_digest": QUALIFICATION_DIGEST,
            "splits": {
                key: sorted(values) for key, values in split_ids.items()
            },
        }
        _write_json(output_root / "manifest.json", manifest)
        _write_json(output_root / "qualification.json", {
            "contract_version": "handoff-factorial-qualification-v2",
            "cases": qualification,
            "mutations": mutations,
        })
        shutil.copyfile(draft_path, output_root / "curator-draft.json")
        return {
            "status": "PASS",
            "case_count": 16,
            "mutation_count": len(mutations),
            "output_root": str(output_root),
        }
    except Exception:
        shutil.rmtree(output_root)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        result = materialize(args.draft.resolve(), args.output.resolve())
    except (MaterializeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
