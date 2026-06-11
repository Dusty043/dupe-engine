from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

from .evaluation import evaluate_matches, match_key_from_pages, truth_to_json
from .models import PageMatch, PageRecord, TruthPair
from .review import annotate_match_for_review, priority_rank, visibility_rank

DEFAULT_CALIBRATION_THRESHOLDS = [0.0, 0.6, 0.7, 0.74, 0.8, 0.86, 0.9, 0.94, 0.97, 0.99]


def parse_thresholds(value: str | None) -> list[float]:
    if not value:
        return list(DEFAULT_CALIBRATION_THRESHOLDS)
    thresholds: list[float] = []
    for raw in value.split(","):
        token = raw.strip()
        if not token:
            continue
        try:
            threshold = float(token)
        except ValueError as exc:
            raise ValueError(f"Invalid threshold '{token}' in --calibration-thresholds") from exc
        if threshold < 0 or threshold > 1:
            raise ValueError(f"Threshold {threshold} must be between 0 and 1")
        thresholds.append(threshold)
    return sorted(set(thresholds)) or list(DEFAULT_CALIBRATION_THRESHOLDS)


def build_calibration_report(
    matches: list[PageMatch],
    truth_pairs: list[TruthPair],
    pages: list[PageRecord] | None = None,
    threshold: float = 0.0,
    thresholds: Iterable[float] | None = None,
) -> dict[str, Any]:
    for match in matches:
        if not match.review_rationale:
            annotate_match_for_review(match)

    threshold_values = sorted(set(float(item) for item in (thresholds or DEFAULT_CALIBRATION_THRESHOLDS) if 0 <= float(item) <= 1))
    if threshold not in threshold_values:
        threshold_values.append(float(threshold))
        threshold_values.sort()

    eval_report = evaluate_matches(matches, truth_pairs, threshold=threshold)
    main_review_matches = [match for match in matches if match.visibility == "main_review_list"]
    main_review_eval_report = evaluate_matches(main_review_matches, truth_pairs, threshold=threshold)
    truth_index = build_truth_index(truth_pairs)
    page_index = build_page_index(pages or [])

    candidate_rows = build_candidate_summary_rows(matches, truth_index, threshold=threshold)
    false_positive_rows = build_false_positive_review_rows(matches, truth_index, threshold=threshold)
    false_negative_rows = build_false_negative_review_rows(eval_report["false_negatives"], page_index)
    page_count = len(pages or [])
    sweep_rows = build_threshold_sweep_rows(matches, truth_pairs, threshold_values, page_count=page_count)

    return {
        "schema_version": "dupe_engine_calibration_v0_8",
        "threshold": threshold,
        "thresholds": threshold_values,
        "summary": build_calibration_summary(
            eval_report,
            candidate_rows,
            false_positive_rows,
            false_negative_rows,
            page_count=page_count,
            main_review_eval_summary=main_review_eval_report["summary"],
        ),
        "threshold_sweep": sweep_rows,
        "candidate_summary": candidate_rows,
        "false_positive_review": false_positive_rows,
        "false_negative_review": false_negative_rows,
        "eval_summary": eval_report["summary"],
        "main_review_eval_summary": main_review_eval_report["summary"],
    }


def build_truth_index(truth_pairs: list[TruthPair]) -> dict[tuple[tuple[str, int], tuple[str, int]], TruthPair]:
    return {pair.unordered_key: pair for pair in truth_pairs}


def build_page_index(pages: list[PageRecord]) -> dict[tuple[str, int], PageRecord]:
    return {(page.document_name, page.page_number): page for page in pages}


def build_calibration_summary(
    eval_report: dict[str, Any],
    candidate_rows: list[dict[str, Any]],
    false_positive_rows: list[dict[str, Any]],
    false_negative_rows: list[dict[str, Any]],
    page_count: int = 0,
    main_review_eval_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review_bucket_counts: dict[str, int] = {}
    review_priority_counts: dict[str, int] = {}
    engine_label_counts: dict[str, int] = {}
    visibility_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for row in candidate_rows:
        bucket = str(row["review_bucket"])
        priority = str(row["review_priority"])
        engine_label = str(row["engine_candidate_label"])
        visibility = str(row["visibility"])
        category = str(row["candidate_category"])
        review_bucket_counts[bucket] = review_bucket_counts.get(bucket, 0) + 1
        review_priority_counts[priority] = review_priority_counts.get(priority, 0) + 1
        engine_label_counts[engine_label] = engine_label_counts.get(engine_label, 0) + 1
        visibility_counts[visibility] = visibility_counts.get(visibility, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1

    issue_counts: dict[str, int] = {}
    for row in false_positive_rows:
        issue_type = str(row["issue_type"])
        issue_counts[issue_type] = issue_counts.get(issue_type, 0) + 1

    eval_summary = eval_report["summary"]
    main_review_eval_summary = main_review_eval_summary or {}
    known_review_risk_count = (
        int(eval_summary.get("expected_negative_hit_count", 0))
        + int(eval_summary.get("partial_overlap_hit_count", 0))
        + int(eval_summary.get("low_information_ignore_hit_count", 0))
    )

    return {
        "page_count": page_count,
        "candidate_count": len(candidate_rows),
        "candidate_pairs_per_100_pages": safe_div_float(len(candidate_rows) * 100, page_count),
        "main_review_list_candidate_count": visibility_counts.get("main_review_list", 0),
        "main_review_list_pairs_per_100_pages": safe_div_float(visibility_counts.get("main_review_list", 0) * 100, page_count),
        "main_review_true_positive_count": main_review_eval_summary.get("true_positive_count"),
        "main_review_false_negative_count": main_review_eval_summary.get("false_negative_count"),
        "main_review_expected_negative_hit_count": main_review_eval_summary.get("expected_negative_hit_count"),
        "main_review_recall_on_must_match": main_review_eval_summary.get("recall_on_must_match"),
        "secondary_review_candidate_count": visibility_counts.get("secondary_review", 0),
        "low_information_candidate_count": visibility_counts.get("low_information", 0),
        "calibration_only_candidate_count": visibility_counts.get("calibration_only", 0),
        "false_positive_review_count": len(false_positive_rows),
        "false_negative_review_count": len(false_negative_rows),
        "known_review_risk_count": known_review_risk_count,
        "engine_candidate_label_counts": engine_label_counts,
        "review_bucket_counts": review_bucket_counts,
        "review_priority_counts": review_priority_counts,
        "candidate_visibility_counts": visibility_counts,
        "candidate_category_counts": category_counts,
        "false_positive_issue_counts": issue_counts,
        "recall_on_must_match": eval_summary.get("recall_on_must_match"),
        "known_negative_hit_rate": eval_summary.get("known_negative_hit_rate"),
        "unknown_prediction_count": eval_summary.get("unknown_prediction_count"),
    }


def build_candidate_summary_rows(
    matches: list[PageMatch],
    truth_index: dict[tuple[tuple[str, int], tuple[str, int]], TruthPair],
    threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    filtered = [match for match in matches if match.confidence >= threshold]
    filtered.sort(
        key=lambda match: (visibility_rank(match.visibility), priority_rank(match.review_priority), match.confidence),
        reverse=True,
    )
    for rank, match in enumerate(filtered, start=1):
        truth = truth_index.get(match_key(match))
        rows.append(match_row_base(match, rank=rank, truth=truth))
    return rows


def build_false_positive_review_rows(
    matches: list[PageMatch],
    truth_index: dict[tuple[tuple[str, int], tuple[str, int]], TruthPair],
    threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for match in matches:
        if match.confidence < threshold:
            continue
        truth = truth_index.get(match_key(match))
        if truth is None:
            issue_type = "unlabeled_prediction"
            reason = "candidate has no pair-level truth label; sample these to estimate candidate explosion and hidden false positives"
        elif truth.label == "duplicate":
            continue
        elif truth.label == "not_duplicate":
            issue_type = "known_negative_hit"
            reason = truth.notes or "truth labels this pair as not_duplicate"
        elif truth.label == "partial_overlap":
            issue_type = "partial_overlap_hit"
            reason = truth.notes or "truth labels this pair as partial_overlap, not a full duplicate"
        elif truth.label == "low_information_ignore":
            issue_type = "low_information_ignore_hit"
            reason = truth.notes or "truth labels this pair as low-information and not useful for duplicate review"
        else:
            issue_type = f"truth_{truth.label}_hit"
            reason = truth.notes or "truth label is not a duplicate"

        base = match_row_base(match, rank=None, truth=truth)
        base.update({"issue_type": issue_type, "review_reason": reason})
        rows.append(base)

    rows.sort(
        key=lambda row: (visibility_rank(str(row["visibility"])), priority_rank(str(row["review_priority"])), float(row["confidence"])),
        reverse=True,
    )
    for idx, row in enumerate(rows, start=1):
        row["rank"] = idx
    return rows


def build_false_negative_review_rows(false_negatives: list[dict[str, Any]], page_index: dict[tuple[str, int], PageRecord]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, item in enumerate(false_negatives, start=1):
        a = item["a"]
        b = item["b"]
        page_a = page_index.get((str(a["document"]), int(a["page"])))
        page_b = page_index.get((str(b["document"]), int(b["page"])))
        reason_missed = classify_false_negative_reason(item, page_a, page_b)
        next_step = recommend_false_negative_next_step(item, page_a, page_b)
        rows.append(
            {
                "rank": idx,
                "pair_id": item.get("pair_id", ""),
                "truth_label": item.get("label", "duplicate"),
                "truth_kind": item.get("type", "unspecified"),
                "expected_min_layer": item.get("expected_min_layer", ""),
                "difficulty": item.get("difficulty", ""),
                "reason_tags": ";".join(str(tag) for tag in item.get("reason_tags", []) or []),
                "reason_missed": reason_missed,
                "a_document": a["document"],
                "a_page": a["page"],
                "b_document": b["document"],
                "b_page": b["page"],
                "notes": item.get("notes", ""),
                "recommended_next_step": next_step,
                "a_text_source": page_text_attr(page_a, "text_source"),
                "b_text_source": page_text_attr(page_b, "text_source"),
                "a_best_word_count": page_int_attr(page_a, "best_word_count"),
                "b_best_word_count": page_int_attr(page_b, "best_word_count"),
                "a_native_text_status": page_text_attr(page_a, "native_text_status"),
                "b_native_text_status": page_text_attr(page_b, "native_text_status"),
                "a_ocr_route": page_text_attr(page_a, "ocr_route"),
                "b_ocr_route": page_text_attr(page_b, "ocr_route"),
                "a_tesseract_attempted": page_bool_attr(page_a, "tesseract_attempted"),
                "b_tesseract_attempted": page_bool_attr(page_b, "tesseract_attempted"),
                "a_tesseract_usable": page_bool_attr(page_a, "tesseract_usable"),
                "b_tesseract_usable": page_bool_attr(page_b, "tesseract_usable"),
                "a_openai_ocr_selected": page_bool_attr(page_a, "openai_ocr_selected"),
                "b_openai_ocr_selected": page_bool_attr(page_b, "openai_ocr_selected"),
                "a_openai_ocr_skip_reason": page_text_attr(page_a, "openai_ocr_skip_reason"),
                "b_openai_ocr_skip_reason": page_text_attr(page_b, "openai_ocr_skip_reason"),
                "a_low_information": page_bool_attr(page_a, "is_low_information"),
                "b_low_information": page_bool_attr(page_b, "is_low_information"),
            }
        )
    return rows


def build_threshold_sweep_rows(
    matches: list[PageMatch],
    truth_pairs: list[TruthPair],
    thresholds: Iterable[float],
    page_count: int = 0,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for threshold in thresholds:
        eval_report = evaluate_matches(matches, truth_pairs, threshold=threshold)
        summary = eval_report["summary"]
        predicted = int(summary.get("predicted_match_count", 0))
        tp = int(summary.get("true_positive_count", 0))
        known_negative = int(summary.get("expected_negative_hit_count", 0))
        partial = int(summary.get("partial_overlap_hit_count", 0))
        low_info = int(summary.get("low_information_ignore_hit_count", 0))
        filtered = [match for match in matches if match.confidence >= threshold]
        visibility_counts = count_match_attr(filtered, "visibility")
        main_eval_report = evaluate_matches(
            [match for match in filtered if match.visibility == "main_review_list"],
            truth_pairs,
            threshold=threshold,
        )
        main_summary = main_eval_report["summary"]
        rows.append(
            {
                "threshold": round(float(threshold), 4),
                "predicted_match_count": predicted,
                "candidate_pairs_per_100_pages": safe_div_float(predicted * 100, page_count),
                "main_review_list_count": visibility_counts.get("main_review_list", 0),
                "main_review_list_pairs_per_100_pages": safe_div_float(visibility_counts.get("main_review_list", 0) * 100, page_count),
                "main_review_true_positive_count": int(main_summary.get("true_positive_count", 0)),
                "main_review_false_negative_count": int(main_summary.get("false_negative_count", 0)),
                "main_review_expected_negative_hit_count": int(main_summary.get("expected_negative_hit_count", 0)),
                "main_review_recall_on_must_match": main_summary.get("recall_on_must_match"),
                "secondary_review_candidate_count": visibility_counts.get("secondary_review", 0),
                "low_information_candidate_count": visibility_counts.get("low_information", 0),
                "calibration_only_candidate_count": visibility_counts.get("calibration_only", 0),
                "true_positive_count": tp,
                "false_negative_count": int(summary.get("false_negative_count", 0)),
                "expected_negative_hit_count": known_negative,
                "partial_overlap_hit_count": partial,
                "low_information_ignore_hit_count": low_info,
                "unknown_prediction_count": int(summary.get("unknown_prediction_count", 0)),
                "recall_on_must_match": summary.get("recall_on_must_match"),
                "known_negative_hit_rate": summary.get("known_negative_hit_rate"),
                "known_review_risk_count": known_negative + partial + low_info,
                "review_load_per_true_positive": safe_div(predicted, tp),
            }
        )
    return rows


def match_key(match: PageMatch) -> tuple[tuple[str, int], tuple[str, int]]:
    return match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number)


def match_row_base(match: PageMatch, rank: int | None, truth: TruthPair | None) -> dict[str, Any]:
    truth_label = truth.label if truth else "unlabeled"
    truth_kind = truth.kind if truth else "unlabeled"
    truth_notes = truth.notes if truth else ""
    signal_text = "; ".join(f"{signal.name}={signal.score:.4f}" for signal in match.signals)
    pass_text = "; ".join(
        f"{record.pass_name}:{'yes' if record.matched else 'no'}"
        for record in match.deterministic_passes
    )
    return {
        "rank": rank or "",
        "truth_label": truth_label,
        "truth_kind": truth_kind,
        "truth_notes": truth_notes,
        "review_bucket": match.review_bucket,
        "engine_candidate_label": match.engine_candidate_label,
        "adjudicator_suggested_label": match.adjudicator_suggested_label or "",
        "human_final_label": match.human_final_label or "",
        "visibility": match.visibility,
        "visibility_reason": match.visibility_reason,
        "candidate_category": match.candidate_category,
        "review_priority": match.review_priority,
        "review_rationale": match.review_rationale,
        "match_type": match.match_type,
        "confidence": round(match.confidence, 4),
        "candidate_stage": match.candidate_stage,
        "recommendation": match.recommendation,
        "a_document": match.page_a.document_name,
        "a_page": match.page_a.page_number,
        "b_document": match.page_b.document_name,
        "b_page": match.page_b.page_number,
        "a_text_source": match.page_a.text_source,
        "b_text_source": match.page_b.text_source,
        "a_best_word_count": match.page_a.best_word_count,
        "b_best_word_count": match.page_b.best_word_count,
        "a_ocr_route": match.page_a.ocr_route,
        "b_ocr_route": match.page_b.ocr_route,
        "a_tesseract_attempted": match.page_a.tesseract_attempted,
        "b_tesseract_attempted": match.page_b.tesseract_attempted,
        "a_tesseract_usable": match.page_a.tesseract_usable,
        "b_tesseract_usable": match.page_b.tesseract_usable,
        "a_openai_ocr_selected": match.page_a.openai_ocr_selected,
        "b_openai_ocr_selected": match.page_b.openai_ocr_selected,
        "a_openai_ocr_skip_reason": match.page_a.openai_ocr_skip_reason or "",
        "b_openai_ocr_skip_reason": match.page_b.openai_ocr_skip_reason or "",
        "a_low_information": match.page_a.is_low_information,
        "b_low_information": match.page_b.is_low_information,
        "signals": signal_text,
        "deterministic_passes": pass_text,
        "embedding_escalation": match.escalation.embedding_required,
        "llm_detector_escalation": match.escalation.llm_detector_required,
        "adjudicator_escalation": match.escalation.adjudicator_required,
    }


def classify_false_negative_reason(item: dict[str, Any], page_a: PageRecord | None, page_b: PageRecord | None) -> str:
    pages = [page for page in (page_a, page_b) if page is not None]
    if len(pages) < 2:
        return "truth_identity_or_ingest_mismatch"
    if any(page.openai_ocr_selected and not page.openai_ocr_usable for page in pages):
        return "fallback_selected_but_still_weak"
    if any(page_has_no_or_weak_text_for_fn(page) and not page.openai_ocr_selected for page in pages):
        return "fallback_not_selected"
    if any(page.is_low_information for page in pages):
        return "low_information_suppressed_or_template"
    expected = str(item.get("expected_min_layer") or "").lower()
    if expected in {"embedding", "llm_adjudication", "human_review"}:
        return "semantic_or_adjudication_layer_miss"
    if expected in {"ocr", "vision_fallback"}:
        return "ocr_or_vision_layer_miss"
    return "deterministic_threshold_or_candidate_generation_miss"


def page_has_no_or_weak_text_for_fn(page: PageRecord) -> bool:
    return page.best_word_count < 12 or page.best_text_source in {"none", "native"} or page.ocr_route in {"tesseract_weak", "tesseract_unavailable"}


def recommend_false_negative_next_step(item: dict[str, Any], page_a: PageRecord | None, page_b: PageRecord | None) -> str:
    kind = str(item.get("type", "")).lower()
    notes = str(item.get("notes", "")).lower()
    page_text_weak = any(
        page is not None and (page.native_text_status != "usable" or page.best_word_count < 25)
        for page in (page_a, page_b)
    )
    page_visual_only = any(page is not None and page.best_word_count == 0 for page in (page_a, page_b))

    if page_visual_only or page_text_weak or any(term in kind + " " + notes for term in ["ocr", "scan", "fax", "camera", "degraded"]):
        return "enable/tune OCR first; then rerun deterministic text and visual matching"
    if "same_text" in kind or "format" in kind:
        return "inspect text normalization and multipass_text_top_k/loose_tfidf_threshold"
    if "partial" in kind:
        return "add separate partial-overlap detector/report bucket instead of forcing duplicate recall"
    return "inspect threshold bands, top-k budget, and whether embeddings should support this candidate family"


def page_text_attr(page: PageRecord | None, attr: str) -> str:
    return str(getattr(page, attr, "")) if page is not None else ""


def page_int_attr(page: PageRecord | None, attr: str) -> int | str:
    return int(getattr(page, attr, 0)) if page is not None else ""


def page_bool_attr(page: PageRecord | None, attr: str) -> bool | str:
    return bool(getattr(page, attr, False)) if page is not None else ""


def safe_div(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def safe_div_float(numerator: float, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(float(numerator) / denominator, 4)


def count_match_attr(matches: list[PageMatch], attr: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for match in matches:
        key = str(getattr(match, attr, ""))
        counts[key] = counts.get(key, 0) + 1
    return counts


def write_rows_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = collect_fieldnames(rows)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def collect_fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    preferred = [
        "rank",
        "issue_type",
        "truth_label",
        "truth_kind",
        "review_bucket",
        "engine_candidate_label",
        "adjudicator_suggested_label",
        "human_final_label",
        "visibility",
        "visibility_reason",
        "candidate_category",
        "review_priority",
        "match_type",
        "confidence",
        "candidate_stage",
        "a_document",
        "a_page",
        "b_document",
        "b_page",
        "review_reason",
        "recommended_next_step",
        "signals",
        "deterministic_passes",
    ]
    seen = set()
    fieldnames: list[str] = []
    for name in preferred:
        if any(name in row for row in rows):
            fieldnames.append(name)
            seen.add(name)
    for row in rows:
        for name in row:
            if name not in seen:
                fieldnames.append(name)
                seen.add(name)
    return fieldnames or ["empty"]
