from __future__ import annotations

import argparse
from pathlib import Path

from dupe_engine.calibration_harness import build_initial_plan, run_calibration
from dupe_engine.config import EngineConfig
from dupe_engine.models import PageRecord
from dupe_engine.ocr import parse_openai_ocr_reason_quotas, select_openai_ocr_pages


def make_page(page: int, *, route: str = "tesseract_weak", vision: bool = False, words: int = 0) -> PageRecord:
    record = PageRecord(
        group="T",
        document_id=f"doc_{page}",
        document_name=f"doc_{page}.pdf",
        page_number=page,
        image_path="/tmp/page.png",
    )
    record.native_text_status = "missing" if words == 0 else "weak"
    record.tesseract_attempted = True
    record.tesseract_usable = False
    record.ocr_route = route
    record.best_word_count = words
    record.meta["vision_fallback_expected"] = vision
    return record


def test_reason_quota_parser_allocates_budget() -> None:
    quotas = parse_openai_ocr_reason_quotas("vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20", 50)
    assert sum(quotas.values()) == 50
    assert quotas["vision_expected"] == 15
    assert quotas["weak_tesseract"] == 15
    assert quotas["no_text"] == 10
    assert quotas["candidate_based"] == 10


def test_reason_balanced_selection_does_not_use_only_vision_bucket() -> None:
    pages = [make_page(i, vision=True, words=3) for i in range(1, 11)]
    pages += [make_page(i, vision=False, words=5) for i in range(11, 21)]
    pages += [make_page(i, vision=False, words=0) for i in range(21, 31)]
    config = EngineConfig(
        openai_ocr_selection_mode="reason_balanced",
        openai_ocr_reason_quotas="vision_expected:10,weak_tesseract:10,no_text:10,candidate_based:0",
        openai_ocr_max_pages_per_job=9,
        openai_ocr_max_pages_per_document=2,
    )
    selected = select_openai_ocr_pages([], config, pages=pages)
    reasons = [reason.split(";")[0] for _page, reason in selected]
    assert len(selected) == 9
    assert any(reason == "vision_expected selection" for reason in reasons)
    assert any(reason == "weak_tesseract selection" for reason in reasons)
    assert any(reason == "no_text selection" for reason in reasons)


def test_calibration_plan_includes_staged_runs() -> None:
    plan = build_initial_plan("balanced", ["control", "ocr", "vector", "queue"], max_runs=None)
    assert len(plan) == 16
    assert any(spec.stage == "control" and spec.vector_profile == "v097_control" and spec.tesseract_profiles == "standard" for spec in plan)
    assert any(spec.stage == "ocr" and spec.ocr_selection_mode == "reason_balanced" for spec in plan)
    assert any(spec.stage == "vector" and spec.vector_profile == "recall_first" for spec in plan)
    assert any(spec.stage == "queue" and spec.queue_profile == "recall_first" for spec in plan)


def test_calibrate_dry_run_writes_manifest(tmp_path: Path) -> None:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    truth = tmp_path / "truth.json"
    truth.write_text('{"must_match": []}', encoding="utf-8")
    args = argparse.Namespace(
        pdf_dir=str(pdf_dir),
        truth=str(truth),
        out_dir=str(tmp_path / "calibration"),
        profile="balanced",
        stages="control,ocr,vector,queue",
        max_runs=2,
        resume=False,
        skip_existing=False,
        dry_run=True,
        confirm_live_ai=False,
        dpi=150,
        tesseract_profiles="standard",
    )
    result = run_calibration(args)
    assert result["executed"] is False
    assert (tmp_path / "calibration" / "calibration_manifest.json").exists()
    assert (tmp_path / "calibration" / "scorecard.csv").exists()


def test_accuracy_first_plan_focuses_on_high_recall_caps() -> None:
    plan = build_initial_plan("accuracy_first", ["control", "ocr", "vector", "queue"], max_runs=None)
    assert len(plan) == 13
    assert any(spec.stage == "ocr" and spec.ocr_cap == 150 and spec.ocr_selection_mode == "reason_balanced" for spec in plan)
    assert any(spec.stage == "vector" and spec.ocr_cap == 150 and spec.vector_profile == "recall_first" for spec in plan)
    assert any(spec.stage == "queue" and spec.ocr_cap == 150 and spec.queue_profile == "recall_first" for spec in plan)
    assert all(spec.openai_ocr_max_pages_per_document in {5, 8} for spec in plan)
