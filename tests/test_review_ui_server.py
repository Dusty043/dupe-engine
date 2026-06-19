import json
from pathlib import Path

import pytest

from dupe_engine.review_ui_server import (
    ReviewJobStore,
    ReviewUiError,
    build_engine_job_command,
    normalize_decision,
    sanitize_upload_filename,
    upsert_review_decisions,
    validate_run_dir,
)


def write_minimal_run_dir(path: Path) -> None:
    payloads = {
        "run_manifest.json": {"schema_version": "dupe_engine_ui_run_v0_8_6", "summary": {}},
        "pages.json": {"schema_version": "dupe_engine_pages_v0_8_6", "pages": []},
        "candidates.json": {"schema_version": "dupe_engine_candidates_v0_8_6", "candidates": [{"candidate_id": "cand_1"}]},
        "capabilities.json": {},
        "metrics.json": {"schema_version": "dupe_engine_metrics_v0_8_6", "summary": {}},
        "review_decisions.json": {"schema_version": "dupe_engine_review_decisions_v0_8_6", "decisions": []},
    }
    path.mkdir(parents=True)
    for name, payload in payloads.items():
        (path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_validate_run_dir_accepts_minimal_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_minimal_run_dir(run_dir)

    validate_run_dir(run_dir)


def test_validate_run_dir_rejects_missing_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()

    with pytest.raises(ReviewUiError):
        validate_run_dir(run_dir)


def test_normalize_decision_rejects_unknown_label() -> None:
    with pytest.raises(ReviewUiError):
        normalize_decision({"candidate_id": "cand_1", "human_label": "delete_it"})


def test_upsert_review_decisions_writes_by_candidate_id(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_minimal_run_dir(run_dir)

    upsert_review_decisions(
        run_dir,
        {
            "decision": {
                "candidate_id": "cand_1",
                "human_label": "duplicate",
                "reviewer_note": "first",
                "reviewed_at": "2026-05-28T00:00:00Z",
            }
        },
    )
    updated = upsert_review_decisions(
        run_dir,
        {
            "decision": {
                "candidate_id": "cand_1",
                "human_label": "not_duplicate",
                "reviewer_note": "corrected",
                "reviewed_at": "2026-05-28T00:01:00Z",
            }
        },
    )

    assert len(updated["decisions"]) == 1
    assert updated["decisions"][0]["human_label"] == "not_duplicate"
    assert json.loads((run_dir / "review_decisions.json").read_text())["decisions"][0]["reviewer_note"] == "corrected"



def test_sanitize_upload_filename_rejects_non_pdf() -> None:
    with pytest.raises(ReviewUiError):
        sanitize_upload_filename("notes.txt")


def test_sanitize_upload_filename_strips_paths() -> None:
    assert sanitize_upload_filename("../Incoming Records (1).pdf") == "Incoming Records (1).pdf"
    assert sanitize_upload_filename("folder\\bad:name.pdf") == "bad_name.pdf"


def test_build_engine_job_command_includes_upload_run_artifacts(tmp_path: Path) -> None:
    command = build_engine_job_command(
        received_dir=tmp_path / "input" / "received_records",
        ere_dir=tmp_path / "input" / "ere_records",
        work_dir=tmp_path / "work",
        run_dir=tmp_path / "run",
        results_path=tmp_path / "results.json",
        settings={"dpi": 150, "ocr": True, "tesseract_profiles": "standard"},
    )
    assert "compare-ab" in command
    assert "--run-dir" in command
    assert str(tmp_path / "run") in command
    assert "--ocr" in command
    assert "--require-ocr" in command
    assert "--openai-ocr" in command
    assert "--openai-ocr-live" in command
    assert "--require-openai-ocr" in command
    assert "--tesseract-profiles" in command


def test_review_job_store_tracks_current_run(tmp_path: Path) -> None:
    store = ReviewJobStore(workspace_dir=tmp_path / "workspace")
    assert store.get_current_run() is None
    run_dir = tmp_path / "run"
    store.set_current_run(run_dir)
    assert store.get_current_run() == run_dir.resolve()
