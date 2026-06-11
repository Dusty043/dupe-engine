from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from .evaluation import evaluate_matches, match_key_from_pages
from .models import PageMatch, PageRecord, TruthPair
from .ocr import ocr_key_token_count
from .text import tokenize_for_similarity

OCR_TERMS = {"ocr", "scan", "scanned", "fax", "camera", "image", "degraded", "raster", "photo"}
OCR_TEXT_SOURCES = {"tesseract_ocr", "openai_ocr"}


def build_ocr_validation_report(
    pages: list[PageRecord],
    matches: list[PageMatch],
    truth_pairs: list[TruthPair] | None = None,
    threshold: float = 0.0,
    capabilities: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build v0.8 OCR validation diagnostics.

    This report is intentionally separate from general calibration output. Its
    job is to answer whether OCR was available, where it ran, where it helped,
    and which truth pairs still look OCR-dependent after the run.
    """

    truth_pairs = truth_pairs or []
    filtered_matches = [match for match in matches if match.confidence >= threshold]
    truth_index = {pair.unordered_key: pair for pair in truth_pairs}
    page_index = {(page.document_name, page.page_number): page for page in pages}

    route_rows = build_ocr_route_rows(pages)
    candidate_rows = build_ocr_candidate_rows(filtered_matches, truth_index)
    openai_rows = [row for row in route_rows if row["openai_ocr_selected"] or row["openai_ocr_attempted"]]
    summary = build_ocr_summary(pages, filtered_matches, truth_pairs, page_index, threshold)

    report: dict[str, Any] = {
        "schema_version": "dupe_engine_ocr_validation_v0_10_1",
        "threshold": threshold,
        "summary": summary,
        "ocr_route_rows": route_rows,
        "ocr_candidate_rows": candidate_rows,
        "openai_ocr_escalation_rows": openai_rows,
    }
    if capabilities is not None:
        report["capabilities"] = capabilities
    if truth_pairs:
        report["ocr_truth_pairs"] = build_ocr_truth_rows(truth_pairs, page_index, filtered_matches)
        report["ocr_false_negative_rows"] = [row for row in report["ocr_truth_pairs"] if row["truth_label"] == "duplicate" and not row["predicted"]]
        report["ocr_ready_missed_candidate_rows"] = build_ocr_ready_missed_candidate_rows(truth_pairs, page_index, filtered_matches)
    return report


def build_ocr_summary(
    pages: list[PageRecord],
    matches: list[PageMatch],
    truth_pairs: list[TruthPair],
    page_index: dict[tuple[str, int], PageRecord],
    threshold: float,
) -> dict[str, Any]:
    native_status_counts = Counter(page.native_text_status or "unknown" for page in pages)
    best_source_counts = Counter(page.best_text_source or "unknown" for page in pages)
    text_source_counts = Counter(page.text_source or "unknown" for page in pages)
    route_counts = Counter(page.ocr_route or "unknown" for page in pages)

    weak_or_missing = [page for page in pages if page.native_text_status in {"weak", "missing"}]
    tesseract_improved = [page for page in pages if page.best_text_source == "tesseract_ocr" and page.best_word_count > page.native_word_count]
    openai_improved = [page for page in pages if page.best_text_source == "openai_ocr" and page.best_word_count > page.native_word_count]
    openai_sidecar = [page for page in pages if page.openai_ocr_usable and bool((page.openai_ocr_text or "").strip())]
    remaining_weak = [page for page in pages if page.native_text_status in {"weak", "missing"} and page_candidate_word_count(page) < 25]
    total_word_gain = sum(max(0, page_candidate_word_count(page) - page.native_word_count) for page in pages)

    ocr_matches = [match for match in matches if match_uses_ocr(match)]
    weak_text_matches = [match for match in matches if match_has_weak_text(match)]

    summary: dict[str, Any] = {
        "page_count": len(pages),
        "candidate_count_at_threshold": len(matches),
        "threshold": threshold,
        "native_text_status_counts": dict(sorted(native_status_counts.items())),
        "best_text_source_counts": dict(sorted(best_source_counts.items())),
        "text_source_counts": dict(sorted(text_source_counts.items())),
        "ocr_route_counts": dict(sorted(route_counts.items())),
        "native_weak_or_missing_pages": len(weak_or_missing),
        "tesseract_attempted_pages": sum(1 for page in pages if page.tesseract_attempted),
        "tesseract_usable_pages": sum(1 for page in pages if page.tesseract_usable),
        "tesseract_improved_pages": len(tesseract_improved),
        "openai_ocr_selected_pages": sum(1 for page in pages if bool(page.openai_ocr_selected)),
        "openai_ocr_attempted_pages": sum(1 for page in pages if page.openai_ocr_attempted),
        "openai_ocr_usable_pages": sum(1 for page in pages if page.openai_ocr_usable),
        "openai_ocr_improved_pages": len(openai_improved),
        "openai_ocr_sidecar_evidence_pages": len(openai_sidecar),
        "source_safe_candidate_ready_pages": sum(1 for page in pages if page_has_source_safe_candidate_evidence(page)),
        "openai_ocr_skip_reason_counts": dict(sorted(Counter(page.openai_ocr_skip_reason or "selected_not_attempted" for page in pages if page.openai_ocr_selected and not page.openai_ocr_attempted).items())),
        "openai_ocr_selection_reason_counts": dict(sorted(Counter((page.openai_ocr_selection_reason or "unknown").split(";")[0].strip() for page in pages if page.openai_ocr_selected).items())),
        "pages_remaining_weak_after_ocr": len(remaining_weak),
        "total_ocr_word_gain": total_word_gain,
        "matches_using_ocr_text": len(ocr_matches),
        "matches_with_weak_or_missing_text": len(weak_text_matches),
    }

    if truth_pairs:
        eval_report = evaluate_matches(matches, truth_pairs, threshold=threshold)
        ocr_truth_pairs = [pair for pair in truth_pairs if pair.label == "duplicate" and truth_pair_is_ocr_dependent(pair, page_index)]
        ocr_truth_keys = {pair.unordered_key for pair in ocr_truth_pairs}
        predicted_keys = {
            match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number)
            for match in matches
            if match.confidence >= threshold
        }
        ocr_truth_hits = ocr_truth_keys & predicted_keys
        all_duplicate_truth = [pair for pair in truth_pairs if pair.label == "duplicate"]
        ocr_ready_missed = [
            pair
            for pair in all_duplicate_truth
            if pair.unordered_key not in predicted_keys and truth_pair_is_ocr_ready(pair, page_index)
        ]
        summary.update(
            {
                "truth_duplicate_count": len(all_duplicate_truth),
                "truth_ocr_dependent_duplicate_count": len(ocr_truth_pairs),
                "truth_ocr_dependent_true_positive_count": len(ocr_truth_hits),
                "truth_ocr_dependent_false_negative_count": len(ocr_truth_keys - predicted_keys),
                "truth_ocr_dependent_recall": safe_div(len(ocr_truth_hits), len(ocr_truth_pairs)),
                "overall_recall_on_must_match": eval_report["summary"].get("recall_on_must_match"),
                "ocr_ready_but_not_candidate_generated_count": len(ocr_ready_missed),
            }
        )
    return summary


def build_ocr_route_rows(pages: list[PageRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        tesseract_gain = max(0, int(page.tesseract_word_count or 0) - int(page.native_word_count or 0))
        best_gain = max(0, int(page.best_word_count or 0) - int(page.native_word_count or 0))
        rows.append(
            {
                "document": page.document_name,
                "page": page.page_number,
                "page_id": page.page_id,
                "native_text_status": page.native_text_status,
                "native_word_count": page.native_word_count,
                "best_text_source": page.best_text_source,
                "best_word_count": page.best_word_count,
                "best_word_gain_over_native": best_gain,
                "ocr_route": page.ocr_route,
                "tesseract_attempted": page.tesseract_attempted,
                "tesseract_usable": page.tesseract_usable,
                "tesseract_confidence": page.tesseract_confidence if page.tesseract_confidence is not None else "",
                "tesseract_word_count": page.tesseract_word_count,
                "tesseract_word_gain_over_native": tesseract_gain,
                "tesseract_profile": page.tesseract_profile or "",
                "openai_ocr_selected": bool(page.openai_ocr_selected),
                "openai_ocr_attempted": page.openai_ocr_attempted,
                "openai_ocr_usable": page.openai_ocr_usable,
                "openai_ocr_word_count": page.openai_ocr_word_count,
                "openai_ocr_sidecar_available": bool(page.openai_ocr_usable and (page.openai_ocr_text or "").strip()),
                "source_safe_candidate_word_count": page_candidate_word_count(page),
                "source_safe_key_token_count": page_source_key_token_count(page),
                "openai_ocr_provider": page.openai_ocr_provider or "",
                "openai_ocr_model": page.openai_ocr_model or "",
                "openai_ocr_selection_reason": page.openai_ocr_selection_reason or page.ocr_escalation_reason or "",
                "openai_ocr_skip_reason": page.openai_ocr_skip_reason or "",
                "openai_ocr_error": page.openai_ocr_error or "",
                "is_low_information": page.is_low_information,
                "low_information_reason": page.low_information_reason or "",
            }
        )
    rows.sort(key=lambda row: (str(row["document"]), int(row["page"])))
    return rows


def build_ocr_candidate_rows(
    matches: list[PageMatch],
    truth_index: dict[tuple[tuple[str, int], tuple[str, int]], TruthPair],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    interesting = [match for match in matches if match_uses_ocr(match) or match_has_weak_text(match) or match_openai_selected(match)]
    interesting.sort(key=lambda match: match.confidence, reverse=True)
    for idx, match in enumerate(interesting, start=1):
        key = match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number)
        truth = truth_index.get(key)
        rows.append(
            {
                "rank": idx,
                "truth_label": truth.label if truth else "unlabeled",
                "truth_kind": truth.kind if truth else "unlabeled",
                "match_type": match.match_type,
                "confidence": round(match.confidence, 4),
                "candidate_stage": match.candidate_stage,
                "engine_candidate_label": match.engine_candidate_label,
                "visibility": match.visibility,
                "a_document": match.page_a.document_name,
                "a_page": match.page_a.page_number,
                "b_document": match.page_b.document_name,
                "b_page": match.page_b.page_number,
                "a_native_text_status": match.page_a.native_text_status,
                "b_native_text_status": match.page_b.native_text_status,
                "a_best_text_source": match.page_a.best_text_source,
                "b_best_text_source": match.page_b.best_text_source,
                "a_best_word_count": match.page_a.best_word_count,
                "b_best_word_count": match.page_b.best_word_count,
                "a_source_safe_candidate_word_count": page_candidate_word_count(match.page_a),
                "b_source_safe_candidate_word_count": page_candidate_word_count(match.page_b),
                "a_ocr_route": match.page_a.ocr_route,
                "b_ocr_route": match.page_b.ocr_route,
                "a_tesseract_attempted": match.page_a.tesseract_attempted,
                "b_tesseract_attempted": match.page_b.tesseract_attempted,
                "a_openai_ocr_selected": bool(match.page_a.openai_ocr_selected),
                "b_openai_ocr_selected": bool(match.page_b.openai_ocr_selected),
                "a_openai_ocr_skip_reason": match.page_a.openai_ocr_skip_reason or "",
                "b_openai_ocr_skip_reason": match.page_b.openai_ocr_skip_reason or "",
                "signals": "; ".join(f"{signal.name}={signal.score:.4f}" for signal in match.signals),
            }
        )
    return rows



def build_ocr_ready_missed_candidate_rows(
    truth_pairs: list[TruthPair],
    page_index: dict[tuple[str, int], PageRecord],
    matches: Iterable[PageMatch],
) -> list[dict[str, Any]]:
    predicted_keys = {
        match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number)
        for match in matches
    }
    rows: list[dict[str, Any]] = []
    for pair in truth_pairs:
        if pair.label != "duplicate" or pair.unordered_key in predicted_keys:
            continue
        page_a = page_index.get((pair.a.document, pair.a.page))
        page_b = page_index.get((pair.b.document, pair.b.page))
        if not truth_pair_is_ocr_ready(pair, page_index):
            continue
        rows.append(
            {
                "truth_label": pair.label,
                "truth_kind": pair.kind,
                "notes": pair.notes,
                "a_document": pair.a.document,
                "a_page": pair.a.page,
                "b_document": pair.b.document,
                "b_page": pair.b.page,
                "a_source_safe_candidate_word_count": page_candidate_word_count(page_a),
                "b_source_safe_candidate_word_count": page_candidate_word_count(page_b),
                "a_key_token_count": page_source_key_token_count(page_a),
                "b_key_token_count": page_source_key_token_count(page_b),
                "a_best_text_source": page_text_attr(page_a, "best_text_source"),
                "b_best_text_source": page_text_attr(page_b, "best_text_source"),
                "a_openai_ocr_usable": bool(page_a.openai_ocr_usable) if page_a else False,
                "b_openai_ocr_usable": bool(page_b.openai_ocr_usable) if page_b else False,
                "recommended_next_step": "OCR evidence exists on both sides but no candidate survived generation/controls; inspect source-safe text views, key-token overlap, sequence promotion, and per-page candidate caps",
            }
        )
    rows.sort(key=lambda row: (str(row["truth_kind"]), str(row["a_document"]), int(row["a_page"])))
    return rows


def truth_pair_is_ocr_ready(pair: TruthPair, page_index: dict[tuple[str, int], PageRecord]) -> bool:
    page_a = page_index.get((pair.a.document, pair.a.page))
    page_b = page_index.get((pair.b.document, pair.b.page))
    return page_has_source_safe_candidate_evidence(page_a) and page_has_source_safe_candidate_evidence(page_b)


def page_has_source_safe_candidate_evidence(page: PageRecord | None) -> bool:
    if page is None:
        return False
    if page_candidate_word_count(page) >= 8:
        return True
    return page_source_key_token_count(page) >= 2


def page_candidate_word_count(page: PageRecord | None) -> int:
    if page is None:
        return 0
    text_word_count = len(tokenize_for_similarity("\n".join([page.native_text or "", page.tesseract_text or "", page.openai_ocr_text or "", page.raw_text or "", page.best_text or ""])))
    return max(
        int(page.best_word_count or 0),
        int(page.native_word_count or 0),
        int(page.tesseract_word_count or 0),
        int(page.openai_ocr_word_count or 0),
        text_word_count,
    )


def page_source_key_token_count(page: PageRecord | None) -> int:
    if page is None:
        return 0
    text = "\n".join([page.native_text or "", page.tesseract_text or "", page.openai_ocr_text or "", page.raw_text or "", page.best_text or ""])
    return ocr_key_token_count(text)

def build_ocr_truth_rows(
    truth_pairs: list[TruthPair],
    page_index: dict[tuple[str, int], PageRecord],
    matches: Iterable[PageMatch],
) -> list[dict[str, Any]]:
    predicted_keys = {
        match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number): match
        for match in matches
    }
    rows: list[dict[str, Any]] = []
    for pair in truth_pairs:
        if pair.label != "duplicate":
            continue
        page_a = page_index.get((pair.a.document, pair.a.page))
        page_b = page_index.get((pair.b.document, pair.b.page))
        key = pair.unordered_key
        match = predicted_keys.get(key)
        ocr_dependent = truth_pair_is_ocr_dependent(pair, page_index)
        if not ocr_dependent and match is None:
            continue
        rows.append(
            {
                "truth_label": pair.label,
                "truth_kind": pair.kind,
                "notes": pair.notes,
                "ocr_dependent": ocr_dependent,
                "predicted": match is not None,
                "confidence": round(match.confidence, 4) if match else "",
                "engine_candidate_label": match.engine_candidate_label if match else "",
                "visibility": match.visibility if match else "",
                "a_document": pair.a.document,
                "a_page": pair.a.page,
                "b_document": pair.b.document,
                "b_page": pair.b.page,
                "a_native_text_status": page_text_attr(page_a, "native_text_status"),
                "b_native_text_status": page_text_attr(page_b, "native_text_status"),
                "a_best_text_source": page_text_attr(page_a, "best_text_source"),
                "b_best_text_source": page_text_attr(page_b, "best_text_source"),
                "a_best_word_count": page_int_attr(page_a, "best_word_count"),
                "b_best_word_count": page_int_attr(page_b, "best_word_count"),
                "a_ocr_route": page_text_attr(page_a, "ocr_route"),
                "b_ocr_route": page_text_attr(page_b, "ocr_route"),
                "recommended_next_step": recommend_ocr_truth_next_step(pair, page_a, page_b, match),
            }
        )
    rows.sort(key=lambda row: (not bool(row["ocr_dependent"]), bool(row["predicted"]), str(row["truth_kind"])))
    return rows


def truth_pair_is_ocr_dependent(pair: TruthPair, page_index: dict[tuple[str, int], PageRecord]) -> bool:
    text = f"{pair.kind} {pair.notes}".lower()
    if any(term in text for term in OCR_TERMS):
        return True
    page_a = page_index.get((pair.a.document, pair.a.page))
    page_b = page_index.get((pair.b.document, pair.b.page))
    return any(page_is_ocr_sensitive(page) for page in (page_a, page_b))


def page_is_ocr_sensitive(page: PageRecord | None) -> bool:
    if page is None:
        return False
    if page.native_text_status in {"weak", "missing"}:
        return True
    if page.best_text_source in OCR_TEXT_SOURCES:
        return True
    if page.openai_ocr_usable or page.openai_ocr_word_count > 0:
        return True
    return False


def match_uses_ocr(match: PageMatch) -> bool:
    return (
        match.page_a.best_text_source in OCR_TEXT_SOURCES
        or match.page_b.best_text_source in OCR_TEXT_SOURCES
        or any(signal.name in {"tfidf_tesseract_text_similarity", "tfidf_openai_ocr_text_similarity", "tfidf_combined_text_similarity", "key_token_overlap", "exact_source_text_hash"} for signal in match.signals)
        or match.page_a.openai_ocr_usable
        or match.page_b.openai_ocr_usable
    )


def match_has_weak_text(match: PageMatch) -> bool:
    return bool(
        match.page_a.native_text_status in {"weak", "missing"}
        or match.page_b.native_text_status in {"weak", "missing"}
        or match.page_a.best_word_count < 25
        or match.page_b.best_word_count < 25
    )


def match_openai_selected(match: PageMatch) -> bool:
    return bool(match.page_a.openai_ocr_selected or match.page_b.openai_ocr_selected)


def recommend_ocr_truth_next_step(pair: TruthPair, page_a: PageRecord | None, page_b: PageRecord | None, match: PageMatch | None) -> str:
    if match is not None and match.visibility != "main_review_list":
        return "candidate was found but hidden outside the main list; inspect visibility/budget ranking after OCR"
    if match is not None:
        return "candidate was found; inspect OCR contribution and whether it belongs in main review list"
    weak_pages = [page for page in (page_a, page_b) if page is not None and page.native_text_status in {"weak", "missing"}]
    if weak_pages and any(page.tesseract_attempted and not page.tesseract_usable for page in weak_pages):
        return "Tesseract attempted but weak; tune DPI/preprocessing or test OpenAI OCR fallback on these pages"
    if weak_pages and any(not page.tesseract_attempted for page in weak_pages):
        return "OCR-dependent miss with weak native text; enable Tesseract OCR and rerun"
    if any(page is not None and (page.best_text_source in OCR_TEXT_SOURCES or page.openai_ocr_usable) for page in (page_a, page_b)):
        return "OCR produced source-safe text but pair still missed; inspect multi-view text/key-token candidates, sequence promotion, and candidate caps"
    return "not obviously OCR-dependent from page metadata; inspect visual thresholds or embeddings next"


def page_text_attr(page: PageRecord | None, attr: str) -> str:
    return str(getattr(page, attr, "")) if page is not None else ""


def page_int_attr(page: PageRecord | None, attr: str) -> int | str:
    return int(getattr(page, attr, 0)) if page is not None else ""


def safe_div(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)
