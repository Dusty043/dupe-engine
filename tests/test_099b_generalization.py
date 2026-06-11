from __future__ import annotations

import argparse
from pathlib import Path

from dupe_engine.calibration_harness import build_generalization_summary, build_initial_plan, run_calibration
from dupe_engine.config import EngineConfig
from dupe_engine.models import PageRecord
from dupe_engine.ocr import should_accept_openai_ocr_result


def test_generalization_plan_crosses_two_corpora() -> None:
    corpora = [
        {"corpus_id": "v3", "pdf_dir": "/tmp/v3", "truth": "/tmp/v3_truth.json"},
        {"corpus_id": "v4", "pdf_dir": "/tmp/v4", "truth": "/tmp/v4_truth.json"},
    ]

    plan = build_initial_plan("generalization", ["control", "ocr", "vector", "queue"], corpora=corpora)

    assert len(plan) == 10
    assert {spec.corpus_id for spec in plan} == {"v3", "v4"}
    assert {spec.variant_id for spec in plan} == {
        "stable_baseline",
        "evidence_conservative",
        "evidence_balanced_vector",
        "evidence_recall_queue",
        "evidence_high_dpi",
    }
    assert sum(1 for spec in plan if spec.ocr_evidence_upgrade_enabled) == 8
    assert any(spec.variant_id == "evidence_high_dpi" and spec.dpi == 200 for spec in plan)


def test_generalization_summary_prefers_stable_worst_case() -> None:
    rows = [
        {"status": "succeeded", "variant_id": "spiky", "corpus_id": "v3", "strict_recall": 0.80, "any_queue_recall": 0.80, "ocr_dependent_recall": 0.70},
        {"status": "succeeded", "variant_id": "spiky", "corpus_id": "v4", "strict_recall": 0.30, "any_queue_recall": 0.30, "ocr_dependent_recall": 0.25},
        {"status": "succeeded", "variant_id": "steady", "corpus_id": "v3", "strict_recall": 0.58, "any_queue_recall": 0.58, "ocr_dependent_recall": 0.50},
        {"status": "succeeded", "variant_id": "steady", "corpus_id": "v4", "strict_recall": 0.56, "any_queue_recall": 0.56, "ocr_dependent_recall": 0.48},
    ]

    summary = build_generalization_summary(rows)

    assert summary["best_generalized_config"]["variant_id"] == "steady"
    assert summary["best_generalized_config"]["worst_strict_recall"] == 0.56


def test_calibrate_generalization_dry_run_writes_cross_corpus_manifest(tmp_path: Path) -> None:
    v3 = tmp_path / "v3"
    v4 = tmp_path / "v4"
    v3.mkdir()
    v4.mkdir()
    t3 = tmp_path / "truth_v3.json"
    t4 = tmp_path / "truth_v4.json"
    t3.write_text('{"must_match": []}', encoding="utf-8")
    t4.write_text('{"must_match": []}', encoding="utf-8")
    args = argparse.Namespace(
        pdf_dir=str(v3),
        truth=str(t3),
        out_dir=str(tmp_path / "calibration"),
        profile="generalization",
        stages="control,ocr,vector,queue",
        max_runs=None,
        resume=False,
        skip_existing=False,
        dry_run=True,
        confirm_live_ai=False,
        dpi=150,
        tesseract_profiles="standard",
        corpus_id="v3",
        secondary_pdf_dir=str(v4),
        secondary_truth=str(t4),
        secondary_corpus_id="v4",
        only_run=None,
    )

    result = run_calibration(args)

    assert result["planned_run_count"] == 10
    manifest = (tmp_path / "calibration" / "calibration_manifest.json").read_text(encoding="utf-8")
    assert '"corpus_id": "v3"' in manifest
    assert '"corpus_id": "v4"' in manifest


def test_openai_ocr_evidence_upgrade_accepts_short_key_token_text() -> None:
    page = PageRecord(
        group="A",
        document_id="doc",
        document_name="doc.pdf",
        page_number=1,
        image_path="/tmp/page.png",
        raw_text="ZXCVBNM123456 garbage unreadable scan text",
        native_text_status="weak",
    )
    text = "Case Number: AB-123456 DOB: 01/02/1970 Provider treatment"
    config = EngineConfig(
        native_min_usable_words=40,
        tesseract_min_words=40,
        openai_ocr_evidence_upgrade_enabled=True,
        openai_ocr_key_token_acceptance=True,
        openai_ocr_min_key_tokens=2,
    )

    accepted, reason, quality = should_accept_openai_ocr_result(page, text, config)

    assert accepted is True
    assert reason in {"openai_ocr_key_token_evidence_text", "openai_ocr_key_token_supported_text", "openai_ocr_longer_usable_text"}
    assert quality["key_token_count"] >= 2
