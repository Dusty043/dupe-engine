from __future__ import annotations

import argparse
import json
from pathlib import Path

from dupe_engine.calibration_analysis import (
    LlmAnalysisOptions,
    build_analysis_payload,
    run_calibration_llm_analysis,
)
from dupe_engine.calibration_harness import run_calibration


def write_fake_calibration(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "calibration_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "test",
                "profile": "generalization",
                "planned_run_count": 2,
                "corpora": [
                    {"corpus_id": "v3", "pdf_dir": "/tmp/private/path/v3", "truth": "/tmp/v3_truth.json"},
                    {"corpus_id": "v4", "pdf_dir": "/tmp/private/path/v4", "truth": "/tmp/v4_truth.json"},
                ],
                "runs": [
                    {"run_id": "run_001", "corpus_id": "v3", "variant_id": "baseline", "ocr_cap": 150},
                    {"run_id": "run_002", "corpus_id": "v4", "variant_id": "baseline", "ocr_cap": 150},
                ],
            }
        ),
        encoding="utf-8",
    )
    rows = [
        {
            "run_id": "run_001",
            "status": "succeeded",
            "corpus_id": "v3",
            "variant_id": "baseline",
            "strict_recall": 0.62,
            "any_queue_recall": 0.62,
            "ocr_dependent_recall": 0.53,
            "known_negative_hits": 1,
            "unknown_predictions": 200,
            "main_queue_size": 160,
            "secondary_queue_size": 150,
            "openai_ocr_selection_reason_counts": '{"vision_expected selection": 50}',
            "false_negative_reason_counts": '{"fallback_selected_but_still_weak": 22}',
            "reviewable_score": 400.0,
        },
        {
            "run_id": "run_002",
            "status": "succeeded",
            "corpus_id": "v4",
            "variant_id": "baseline",
            "strict_recall": 0.50,
            "any_queue_recall": 0.50,
            "ocr_dependent_recall": 0.47,
            "known_negative_hits": 0,
            "unknown_predictions": 405,
            "main_queue_size": 210,
            "secondary_queue_size": 202,
            "openai_ocr_selection_reason_counts": '{"weak_tesseract selection": 61}',
            "false_negative_reason_counts": '{"fallback_selected_but_still_weak": 35}',
            "reviewable_score": 350.0,
        },
    ]
    (out / "scorecard.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")
    (out / "recommended_configs.json").write_text(
        json.dumps({"recommendations": {"best_by_recall_first_score": rows[0]}, "generalization_summary": {}}),
        encoding="utf-8",
    )


def test_calibration_analysis_payload_is_metrics_only(tmp_path: Path) -> None:
    write_fake_calibration(tmp_path)

    payload = build_analysis_payload(tmp_path)

    assert payload["metrics_only"] is True
    assert payload["manifest"]["corpora"][0]["pdf_dir_name"] == "v3"
    serialized = json.dumps(payload)
    assert "/tmp/private/path" not in serialized
    assert "fallback_selected_but_still_weak" in serialized


def test_run_calibration_llm_analysis_dry_run_writes_reports(tmp_path: Path) -> None:
    write_fake_calibration(tmp_path)

    result = run_calibration_llm_analysis(tmp_path, LlmAnalysisOptions(enabled=True, dry_run=True))

    assert result["status"] == "dry_run"
    assert (tmp_path / "llm_analysis.md").exists()
    assert (tmp_path / "llm_analysis.json").exists()
    assert "Calibration Analysis Report" in (tmp_path / "llm_analysis.md").read_text(encoding="utf-8")


def test_calibrate_dry_run_with_llm_analysis_does_not_execute_analysis(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    truth = tmp_path / "truth.json"
    truth.write_text('{"must_match": []}', encoding="utf-8")
    args = argparse.Namespace(
        pdf_dir=str(corpus),
        truth=str(truth),
        out_dir=str(tmp_path / "calibration"),
        profile="balanced",
        stages="control,ocr,vector,queue",
        max_runs=1,
        resume=False,
        skip_existing=False,
        dry_run=True,
        confirm_live_ai=False,
        dpi=150,
        tesseract_profiles="standard",
        corpus_id=None,
        secondary_pdf_dir=None,
        secondary_truth=None,
        secondary_corpus_id=None,
        only_run=None,
        llm_analysis=True,
        llm_analysis_dry_run=True,
        llm_analysis_include_text_snippets=False,
        llm_analysis_model=None,
        llm_analysis_out=None,
        llm_analysis_json_out=None,
    )

    result = run_calibration(args)

    assert result["planned_run_count"] == 1
    assert result.get("llm_analysis") is None
    assert not (tmp_path / "calibration" / "llm_analysis.md").exists()
