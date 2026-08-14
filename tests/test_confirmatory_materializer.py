from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "materialize_handoff_confirmatory_set.py"
SPEC = importlib.util.spec_from_file_location("confirmatory_materializer", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
VERIFY_SCRIPT = Path(__file__).parents[1] / "scripts" / "verify_handoff_confirmatory_freeze.py"
VERIFY_SPEC = importlib.util.spec_from_file_location("confirmatory_freeze", VERIFY_SCRIPT)
assert VERIFY_SPEC and VERIFY_SPEC.loader
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


def _draft() -> dict:
    difficulties = sorted(MODULE.DIFFICULTIES)
    cases = []
    for index, difficulty in enumerate(difficulties, 1):
        project = "Harbor Finch Survey" if difficulty == "paraphrase" else f"Project {index}"
        base = f"Projects/{project}"
        cases.append({
            "id": f"case-{index:02d}",
            "difficulty": difficulty,
            "project_label": project,
            "question": "Why is work paused?" if difficulty == "paraphrase" else f"State of {project}?",
            "entry_filename": f"{base}/Start.md",
            "entry_body": f"# Entry\n[[{base}/Handoff]]\n",
            "handoff_filename": f"{base}/Handoff.md",
            "handoff_body": f"# Handoff\n[[{base}/Authority]]\n",
            "authority_filename": f"{base}/Authority.md",
            "authority_body": f"# Authority\nSTATE_CODE: S{index}\nNEXT_ACTION_CODE: N{index}\nSTOP_CODE: A{index}\nSTOP_CODE: B{index}\n",
            "state_code": f"S{index}",
            "next_action_code": f"N{index}",
            "stop_condition_codes": [f"A{index}", f"B{index}"],
            "failure_target": "target",
            "rationale": "reason",
        })
    return {
        "contract_version": "handoff-confirmatory-curator-v1",
        "set_id": "test",
        "cases": cases,
        "separation_notes": "new",
    }


def test_materializer_builds_six_case_isolated_corpus(tmp_path: Path) -> None:
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(_draft()), encoding="utf-8")
    output = tmp_path / "set"

    manifest = MODULE.materialize(draft, output)

    assert manifest["status"] == "frozen-unrun"
    assert len(manifest["cases"]) == 6
    assert len(list((output / "cases").glob("*.json"))) == 6
    assert len(list((output / "gold").glob("*.json"))) == 6
    assert list((output / "corpus" / "Archive").rglob("Handoff.md"))
    paraphrase_file = next(
        item["case_file"] for item in manifest["cases"]
        if item["difficulty"] == "paraphrase"
    )
    paraphrase = json.loads((output / paraphrase_file).read_text())
    assert "Harbor Finch Survey" in paraphrase["question"]
    with pytest.raises(ValueError, match="overwrite"):
        MODULE.materialize(draft, output)


@pytest.mark.parametrize("path", ["../escape.md", "/abs.md", "not-markdown.txt"])
def test_materializer_rejects_unsafe_paths(path: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        MODULE._safe_markdown_path(path)


def test_freeze_verifier_detects_asset_and_harness_drift(tmp_path: Path) -> None:
    root, repo = tmp_path / "set", tmp_path / "repo"
    root.mkdir()
    repo.mkdir()
    asset, harness = root / "case.json", repo / "runner.py"
    asset.write_text("case", encoding="utf-8")
    harness.write_text("runner", encoding="utf-8")
    freeze = {
        "contract_version": "handoff-confirmatory-freeze-v1",
        "set_id": "test",
        "status": "frozen-unrun",
        "frozen_date": "2026-08-14",
        "live_subject_runs": 0,
        "assets": {"case.json": hashlib.sha256(asset.read_bytes()).hexdigest()},
        "harness_surface": {"runner.py": hashlib.sha256(harness.read_bytes()).hexdigest()},
        "limitations": [],
    }
    freeze["freeze_digest"] = hashlib.sha256(
        json.dumps(freeze, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode()
    ).hexdigest()
    (root / "freeze.json").write_text(json.dumps(freeze), encoding="utf-8")

    assert VERIFY.verify(root, repo)["status"] == "PASS"
    harness.write_text("mutated", encoding="utf-8")
    result = VERIFY.verify(root, repo)
    assert result["status"] == "FAIL"
    assert result["failures"] == ["harness drift: runner.py"]
