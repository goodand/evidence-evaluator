from __future__ import annotations

import json
from pathlib import Path

from evidence_evaluator.freeze import canonical_digest, sha256_file
from evidence_evaluator.transport_qualification import (
    EXPECTED_CASE_IDS,
    TRANSPORT_SURFACE,
    build_receipt,
    verify_receipt,
    write_receipt,
)


PREFIX = "handoff-confirmatory-v1-requal-current"
MODEL = "gpt-5.6-luna"


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    repo = tmp_path / "repo"
    private = tmp_path / "private"
    results = tmp_path / "results"
    for relative in TRANSPORT_SURFACE:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")

    profile = private / "profile.json"
    _write(profile, {"root": str(private / "corpus")})
    for case_id in EXPECTED_CASE_IDS:
        _write(private / "cases" / f"{case_id}.json", {"id": case_id})
        _write(private / "gold" / f"{case_id}.json", {"case_id": case_id})

    assets = {
        path.relative_to(private).as_posix(): sha256_file(path)
        for path in private.rglob("*")
        if path.is_file()
    }
    unsigned_freeze = {
        "contract_version": "handoff-confirmatory-freeze-v1",
        "assets": assets,
        "harness_surface": {},
    }
    _write(private / "freeze.json", {
        **unsigned_freeze,
        "freeze_digest": canonical_digest(unsigned_freeze),
    })

    for case_id in EXPECTED_CASE_IDS:
        result_path = results / f"{PREFIX}-{case_id}.json"
        audit_path = result_path.with_suffix(".mcp-audit.jsonl")
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text('{"tool":"vault_search"}\n', encoding="utf-8")
        _write(result_path, {
            "case_id": case_id,
            "execution": {"subject_model": MODEL},
            "runtime": {
                "valid": True,
                "provider_trace_matches_audit": True,
                "provider_attempt_count": 3,
                "provider_failed_tools": [],
            },
            "accepted": True,
            "provenance": {
                "case_sha256": sha256_file(private / "cases" / f"{case_id}.json"),
                "gold_sha256": sha256_file(private / "gold" / f"{case_id}.json"),
                "profile_sha256": sha256_file(profile),
                "mcp_audit_sha256": sha256_file(audit_path),
            },
        })
    return repo, private, results


def test_current_transport_receipt_binds_assets_surface_model_and_results(
    tmp_path: Path,
) -> None:
    repo, private, results = _fixture(tmp_path)
    receipt = build_receipt(
        private, repo, results, result_prefix=PREFIX, subject_model=MODEL
    )
    assert receipt["status"] == "PASS"
    assert receipt["accepted_count"] == 6
    assert receipt["invalid_run_count"] == 0
    assert set(receipt["transport_surface"]) == set(TRANSPORT_SURFACE)

    output = tmp_path / "qualification.json"
    write_receipt(receipt, output)
    assert verify_receipt(output, private, repo, results)["status"] == "PASS"

    changed = json.loads((results / f"{PREFIX}-CONF-01.json").read_text())
    changed["accepted"] = False
    _write(results / f"{PREFIX}-CONF-01.json", changed)
    assert verify_receipt(output, private, repo, results)["status"] == "FAIL"


def test_transport_receipt_rejects_wrong_model_and_incomplete_case_set(
    tmp_path: Path,
) -> None:
    repo, private, results = _fixture(tmp_path)
    wrong_model = build_receipt(
        private, repo, results, result_prefix=PREFIX, subject_model="wrong-model"
    )
    assert wrong_model["status"] == "FAIL"
    assert any("subject model mismatch" in item for item in wrong_model["failures"])

    (results / f"{PREFIX}-CONF-06.json").unlink()
    incomplete = build_receipt(
        private, repo, results, result_prefix=PREFIX, subject_model=MODEL
    )
    assert incomplete["status"] == "FAIL"
    assert "result set is not exactly CONF-01..CONF-06" in incomplete["failures"]
