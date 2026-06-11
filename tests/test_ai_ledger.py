from __future__ import annotations

from dupe_engine.ai_ledger import build_ai_call_ledger, ROUTE_TEXT_EMBEDDING, ROUTE_VISION_OCR_EXTRACTION
from dupe_engine.config import EngineConfig
from dupe_engine.embedding_detector import apply_embedding_detector
from dupe_engine.models import EscalationDecision, MatchSignal, PageMatch, PageRecord
from dupe_engine.ocr import apply_openai_ocr_fallback


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
        comparison_text=text,
    )


def make_candidate(page_a: PageRecord, page_b: PageRecord, confidence: float = 0.82) -> PageMatch:
    return PageMatch(
        match_type="near_visual_candidate",
        confidence=confidence,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("perceptual_hash", confidence)],
        candidate_stage="deterministic_standard",
        escalation=EscalationDecision(embedding_required=True, reason="borderline semantic check"),
    )


def test_ai_ledger_records_vision_ocr_dry_run_route() -> None:
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
    page_b = make_page(2, "usable native clinical text medication assessment treatment follow up")
    page_b.native_text_status = "usable"
    match = make_candidate(page_a, page_b)

    changed = apply_openai_ocr_fallback([match], config)
    ledger = build_ai_call_ledger([page_a, page_b], [match])

    assert changed == 0
    assert ledger["summary"]["record_count"] == 1
    assert ledger["summary"]["dry_run_count"] == 1
    record = ledger["records"][0]
    assert record["route"] == ROUTE_VISION_OCR_EXTRACTION
    assert record["status"] == "dry_run_skipped"
    assert record["subject_type"] == "page"
    assert record["input_kind"] == "page_image"
    assert record["selected"] is True
    assert record["attempted"] is False


def test_ai_ledger_records_embedding_dry_run_route() -> None:
    config = EngineConfig(enable_embeddings=True, embeddings_dry_run=True)
    page_a = make_page(1, "clinical medication diagnosis assessment plan follow up imaging results")
    page_b = make_page(2, "clinical medication diagnosis assessment plan follow up imaging results")
    match = make_candidate(page_a, page_b)

    matches = apply_embedding_detector([match], config)
    ledger = build_ai_call_ledger([page_a, page_b], matches)

    assert ledger["summary"]["record_count"] == 1
    assert ledger["summary"]["dry_run_count"] == 1
    record = ledger["records"][0]
    assert record["route"] == ROUTE_TEXT_EMBEDDING
    assert record["status"] == "dry_run_skipped"
    assert record["subject_type"] == "candidate_pair"
    assert record["input_kind"] == "page_text_pair"
    assert record["selected"] is True
    assert record["attempted"] is False
