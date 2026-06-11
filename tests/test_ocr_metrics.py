from __future__ import annotations

from dupe_engine.models import MatchSignal, PageMatch, PageRecord, TruthPageRef, TruthPair
from dupe_engine.ocr_metrics import build_ocr_validation_report


def make_page(document: str, page: int, native_status: str = "usable", source: str = "native", words: int = 40) -> PageRecord:
    return PageRecord(
        group="T",
        document_id=document.replace(".", "_"),
        document_name=document,
        page_number=page,
        image_path=f"/tmp/{document}-{page}.png",
        native_text_status=native_status,
        native_word_count=0 if native_status == "missing" else min(words, 10),
        best_text_source=source,
        best_word_count=words,
        text_source="ocr" if source in {"tesseract_ocr", "openai_ocr"} else source,
        ocr_route="tesseract_usable" if source == "tesseract_ocr" else "native_only",
        tesseract_attempted=source == "tesseract_ocr",
        tesseract_usable=source == "tesseract_ocr",
        tesseract_word_count=words if source == "tesseract_ocr" else 0,
    )


def test_ocr_validation_report_counts_ocr_dependent_truth_hits() -> None:
    page_a = make_page("a.pdf", 1, native_status="missing", source="tesseract_ocr", words=55)
    page_b = make_page("b.pdf", 1, native_status="missing", source="tesseract_ocr", words=54)
    match = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.91,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("tfidf_cosine_similarity", 0.91)],
        candidate_stage="deterministic_strict",
        engine_candidate_label="likely_duplicate",
        visibility="main_review_list",
    )
    truth = [
        TruthPair(
            TruthPageRef("a.pdf", 1),
            TruthPageRef("b.pdf", 1),
            label="duplicate",
            kind="scanned_duplicate",
            notes="OCR required",
        )
    ]

    report = build_ocr_validation_report([page_a, page_b], [match], truth_pairs=truth)

    assert report["summary"]["truth_ocr_dependent_duplicate_count"] == 1
    assert report["summary"]["truth_ocr_dependent_true_positive_count"] == 1
    assert report["summary"]["truth_ocr_dependent_recall"] == 1.0
    assert report["summary"]["tesseract_improved_pages"] == 2
    assert report["ocr_candidate_rows"][0]["truth_label"] == "duplicate"


def test_ocr_validation_report_lists_openai_selected_skips() -> None:
    page = make_page("a.pdf", 1, native_status="missing", source="native", words=0)
    page.openai_ocr_selected = True
    page.openai_ocr_selection_reason = "deterministic candidate confidence 0.80; weak OCR/text on page A"
    page.openai_ocr_skip_reason = "dry_run"
    report = build_ocr_validation_report([page], [], truth_pairs=[])
    rows = report["openai_ocr_escalation_rows"]
    assert len(rows) == 1
    assert rows[0]["openai_ocr_skip_reason"] == "dry_run"
