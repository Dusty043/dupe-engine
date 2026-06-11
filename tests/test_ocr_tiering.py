from __future__ import annotations

from dupe_engine.capabilities import build_capability_report
from dupe_engine.config import EngineConfig
from dupe_engine.models import MatchSignal, PageMatch, PageRecord
from dupe_engine.ocr import classify_native_text, select_openai_ocr_pages, update_best_text


def make_page(page_number: int, text: str = "") -> PageRecord:
    return PageRecord(
        group="T",
        document_id="doc",
        document_name="doc.pdf",
        page_number=page_number,
        image_path="/tmp/page.png",
        native_text=text,
        raw_text=text,
        best_text=text,
    )


def test_native_text_status_uses_word_threshold() -> None:
    config = EngineConfig(native_min_usable_words=3)
    assert classify_native_text("", config) == "missing"
    assert classify_native_text("only two", config) == "weak"
    assert classify_native_text("one two three", config) == "usable"


def test_openai_ocr_dry_run_is_visible_without_api_key() -> None:
    config = EngineConfig(enable_ocr=True, enable_openai_ocr=True, openai_ocr_dry_run=True)
    status = build_capability_report(config).layers["openai_ocr_fallback"]
    assert status.enabled is True
    assert status.available is False
    assert status.status == "dry_run"


def test_openai_ocr_selection_requires_weak_tesseract_candidate() -> None:
    config = EngineConfig(enable_ocr=True, enable_openai_ocr=True, openai_ocr_max_pages_per_job=2)
    page_a = make_page(1)
    page_a.native_text_status = "missing"
    page_a.tesseract_attempted = True
    page_a.tesseract_usable = False
    page_b = make_page(2, "This page has enough native text content to be usable for matching.")
    page_b.native_text_status = "usable"
    match = PageMatch(
        match_type="near_visual_candidate",
        confidence=0.72,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("perceptual_hash", 0.72)],
        candidate_stage="deterministic_loose",
    )
    selected = select_openai_ocr_pages([match], config)
    assert selected[0][0] is page_a
    assert "weak OCR/text" in selected[0][1]


def test_update_best_text_records_openai_ocr_source() -> None:
    config = EngineConfig()
    page = make_page(1)
    update_best_text(page, "diabetes hypertension follow up plan medication refill lumbar spine assessment treatment provider clinic blood pressure normal", "openai_ocr", config)
    assert page.best_text_source == "openai_ocr"
    assert page.text_source == "ocr"
    assert page.best_word_count > 0
    assert page.text_hash is not None

from dupe_engine.ocr import apply_openai_ocr_fallback


def test_openai_ocr_dry_run_records_selected_pages_without_attempting_provider() -> None:
    config = EngineConfig(
        enable_ocr=True,
        enable_openai_ocr=True,
        openai_ocr_dry_run=True,
        openai_ocr_max_pages_per_job=1,
    )
    page_a = make_page(1)
    page_a.native_text_status = "missing"
    page_a.tesseract_attempted = True
    page_a.tesseract_usable = False
    page_b = make_page(2, "usable native text with enough clinical context medication plan assessment follow up")
    page_b.native_text_status = "usable"
    match = PageMatch(
        match_type="near_visual_candidate",
        confidence=0.82,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("perceptual_hash", 0.82)],
        candidate_stage="deterministic_standard",
    )

    changed = apply_openai_ocr_fallback([match], config)

    assert changed == 0
    assert page_a.openai_ocr_selected is True
    assert page_a.openai_ocr_attempted is False
    assert page_a.openai_ocr_skip_reason == "dry_run"
    assert "weak OCR/text" in (page_a.openai_ocr_selection_reason or "")


def test_openai_ocr_default_selects_weak_pages_without_candidate() -> None:
    config = EngineConfig(
        enable_ocr=True,
        enable_openai_ocr=True,
        openai_ocr_selection_mode="weak_pages_or_vision_expected",
        openai_ocr_max_pages_per_job=2,
    )
    page = make_page(3)
    page.native_text_status = "missing"
    page.tesseract_attempted = True
    page.tesseract_usable = False
    page.tesseract_word_count = 0
    page.best_word_count = 0

    selected = select_openai_ocr_pages([], config, pages=[page])

    assert len(selected) == 1
    assert selected[0][0] is page
    assert "selection" in selected[0][1]


def test_openai_ocr_candidate_based_mode_keeps_old_behavior() -> None:
    config = EngineConfig(
        enable_ocr=True,
        enable_openai_ocr=True,
        openai_ocr_selection_mode="candidate_based",
        openai_ocr_max_pages_per_job=2,
    )
    page = make_page(4)
    page.native_text_status = "missing"
    page.tesseract_attempted = True
    page.tesseract_usable = False

    selected = select_openai_ocr_pages([], config, pages=[page])

    assert selected == []
