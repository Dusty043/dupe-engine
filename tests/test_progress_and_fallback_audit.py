import json
from pathlib import Path

from dupe_engine.config import EngineConfig
from dupe_engine.fallback_audit import build_fallback_audit
from dupe_engine.models import PageRecord
from dupe_engine.progress import PROGRESS_ENV, emit_progress, initialize_progress


def make_page(**overrides):
    values = dict(
        group="ALL",
        document_id="doc",
        document_name="doc.pdf",
        page_number=1,
        image_path="page.png",
        native_text_status="missing",
        tesseract_attempted=True,
        tesseract_usable=False,
        tesseract_word_count=0,
        best_word_count=0,
        best_text_source="none",
        ocr_route="tesseract_weak",
    )
    values.update(overrides)
    return PageRecord(**values)


def test_progress_files_are_written(tmp_path, monkeypatch):
    monkeypatch.setenv(PROGRESS_ENV, str(tmp_path))
    initialize_progress(command="eval-all", source_args={"pdf_dir": "corpus"})
    emit_progress(stage="ocr_routing", message="Processed page", current=1, total=4)

    progress = json.loads((tmp_path / "progress.json").read_text())
    assert progress["schema_version"] == "dupe_engine_progress_v0_9_5"
    assert progress["stage"] == "ocr_routing"
    assert progress["percent"] == 0.25
    assert (tmp_path / "progress_events.jsonl").exists()


def test_fallback_audit_counts_selected_and_budget_skips():
    config = EngineConfig(openai_ocr_max_pages_per_job=1, openai_ocr_selection_mode="weak_pages_or_vision_expected")
    selected = make_page(openai_ocr_selected=True, openai_ocr_attempted=True, openai_ocr_usable=True, openai_ocr_word_count=20, best_text_source="openai_ocr", native_word_count=0, best_word_count=20, openai_ocr_selection_reason="weak_pages selection; test")
    eligible = make_page(document_id="doc2", page_number=2)
    usable_native = make_page(document_id="doc3", page_number=3, native_text_status="usable", tesseract_usable=False)

    audit = build_fallback_audit([selected, eligible, usable_native], config)
    summary = audit["summary"]

    assert summary["selected_pages"] == 1
    assert summary["attempted_pages"] == 1
    assert summary["usable_pages"] == 1
    assert summary["eligible_not_selected_pages"] == 1
    assert summary["skipped_due_budget_estimate"] == 1
