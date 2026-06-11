from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .evaluation import evaluate_matches, match_key_from_pages, match_to_prediction_json, safe_div, truth_to_json
from .models import PageMatch, PageRecord, TruthPair


PHASE_EVAL_SCHEMA_VERSION = "dupe_engine_phase_eval_v0_9_8"


def build_phase_eval_report(
    pages: list[PageRecord],
    matches: list[PageMatch],
    truth_pairs: list[TruthPair] | None = None,
    *,
    threshold: float = 0.0,
) -> dict[str, Any]:
    """Build phase-aware evaluation for OCR rescue, vector retrieval, and review burden.

    Strict pair eval is still useful, but it is too blunt for OCR/vector phases.
    This report separates evidence readiness, vector-neighborhood retrieval, and
    reviewer queue pressure so accuracy work can be tuned without treating every
    unjudged retrieval candidate as a final false positive.
    """

    truth_pairs = truth_pairs or []
    predicted = [match for match in matches if match.confidence >= threshold]
    return {
        "schema_version": PHASE_EVAL_SCHEMA_VERSION,
        "threshold": threshold,
        "truth_available": bool(truth_pairs),
        "strict_pair_eval": strict_pair_eval_summary(predicted, truth_pairs, threshold),
        "ocr_rescue_eval": build_ocr_rescue_eval(pages, predicted, truth_pairs),
        "vector_retrieval_eval": build_vector_retrieval_eval(predicted, truth_pairs),
        "review_queue_eval": build_review_queue_eval(predicted, truth_pairs),
        "stage_delta_eval": build_stage_delta_eval(predicted, truth_pairs, threshold),
        "unknown_prediction_buckets": build_unknown_prediction_buckets(predicted, truth_pairs),
        "notes": {
            "strict_pair_eval": "Exact explicit truth-pair scoring. Keep for regression, but do not treat it as the whole post-OCR/vector accuracy picture.",
            "ocr_rescue_eval": "Evidence-readiness metrics: whether OCR/fallback made pages usable enough for downstream matching.",
            "vector_retrieval_eval": "Retrieval-style metrics for embedding/vector candidates: neighborhood coverage and review burden, not final adjudication.",
            "review_queue_eval": "Human workflow view: where true pairs, known negatives, and unjudged candidates landed.",
        },
    }


def strict_pair_eval_summary(matches: list[PageMatch], truth_pairs: list[TruthPair], threshold: float) -> dict[str, Any]:
    if not truth_pairs:
        return {"available": False, "predicted_match_count": len(matches)}
    report = evaluate_matches(matches, truth_pairs, threshold=threshold)
    return {"available": True, **report["summary"]}


def build_ocr_rescue_eval(pages: list[PageRecord], matches: list[PageMatch], truth_pairs: list[TruthPair]) -> dict[str, Any]:
    page_by_key = {(page.document_name, page.page_number): page for page in pages}
    duplicate_pairs = [pair for pair in truth_pairs if pair.label == "duplicate"]
    readiness_counts: Counter[str] = Counter()
    readiness_by_layer: dict[str, Counter[str]] = defaultdict(Counter)
    blocked_pairs: list[dict[str, Any]] = []

    for pair in duplicate_pairs:
        page_a = page_by_key.get(pair.a.key)
        page_b = page_by_key.get(pair.b.key)
        status = truth_pair_ocr_readiness(page_a, page_b)
        readiness_counts[status] += 1
        readiness_by_layer[pair.expected_min_layer or "unspecified"][status] += 1
        if status in {"one_side_unusable", "both_sides_unusable", "missing_page_record"}:
            blocked_pairs.append({"truth": truth_to_json(pair), "ocr_readiness": status})

    openai_selected = [page for page in pages if page.openai_ocr_selected]
    openai_attempted = [page for page in pages if page.openai_ocr_attempted]
    openai_usable = [page for page in pages if page.openai_ocr_usable]
    openai_improved = [page for page in pages if page.ocr_route == "openai_ocr_fallback"]

    return {
        "summary": {
            "page_count": len(pages),
            "native_weak_or_missing_pages": sum(1 for page in pages if page.native_text_status in {"weak", "missing"}),
            "tesseract_attempted_pages": sum(1 for page in pages if page.tesseract_attempted),
            "tesseract_usable_pages": sum(1 for page in pages if page.tesseract_usable),
            "openai_selected_pages": len(openai_selected),
            "openai_attempted_pages": len(openai_attempted),
            "openai_usable_pages": len(openai_usable),
            "openai_improved_pages": len(openai_improved),
            "openai_selection_reason_counts": dict(count_page_attr(openai_selected, "openai_ocr_selection_reason")),
            "truth_duplicate_count": len(duplicate_pairs),
            "truth_pairs_both_sides_usable": readiness_counts.get("both_sides_usable", 0),
            "truth_pairs_one_side_unusable": readiness_counts.get("one_side_unusable", 0),
            "truth_pairs_both_sides_unusable": readiness_counts.get("both_sides_unusable", 0),
            "truth_pairs_missing_page_record": readiness_counts.get("missing_page_record", 0),
            "ocr_ready_pair_rate": safe_div(readiness_counts.get("both_sides_usable", 0), len(duplicate_pairs)),
        },
        "readiness_by_expected_min_layer": {
            layer: {**dict(counts), "total": sum(counts.values())}
            for layer, counts in sorted(readiness_by_layer.items())
        },
        "ocr_blocked_truth_pairs_preview": blocked_pairs[:100],
    }


def truth_pair_ocr_readiness(page_a: PageRecord | None, page_b: PageRecord | None) -> str:
    if page_a is None or page_b is None:
        return "missing_page_record"
    usable_a = page_has_usable_text(page_a)
    usable_b = page_has_usable_text(page_b)
    if usable_a and usable_b:
        return "both_sides_usable"
    if usable_a or usable_b:
        return "one_side_unusable"
    return "both_sides_unusable"


def page_has_usable_text(page: PageRecord) -> bool:
    if page.is_low_information:
        return False
    if page.best_word_count >= 12:
        return True
    if page.tesseract_usable or page.openai_ocr_usable:
        return True
    return False


def build_vector_retrieval_eval(matches: list[PageMatch], truth_pairs: list[TruthPair]) -> dict[str, Any]:
    vector_matches = [match for match in matches if match_has_vector_signal(match)]
    embedding_only = [match for match in vector_matches if match_is_embedding_only(match)]
    truth_duplicates = [pair for pair in truth_pairs if pair.label == "duplicate"]
    known_negatives = {pair.unordered_key: pair for pair in truth_pairs if pair.label == "not_duplicate"}
    vector_by_truth_key = {
        match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number): match
        for match in vector_matches
    }
    page_to_truth_groups = build_page_to_truth_groups(truth_duplicates)
    truth_group_ids = {
        str(pair.raw_metadata.get("truth_group_id"))
        for pair in truth_duplicates
        if pair.raw_metadata.get("truth_group_id")
    }

    recall_at: dict[str, dict[str, Any]] = {}
    for k in [1, 3, 5, 10]:
        hits = []
        for pair in truth_duplicates:
            match = vector_by_truth_key.get(pair.unordered_key)
            if not match:
                continue
            if vector_rank_for_match(match) <= k:
                hits.append(match_to_prediction_json(match))
        group_hits = vector_truth_group_hits(vector_matches, page_to_truth_groups, k)
        recall_at[f"recall_at_{k}"] = {
            "hit_count": len(hits),
            "truth_duplicate_count": len(truth_duplicates),
            "recall": safe_div(len(hits), len(truth_duplicates)),
        }
        recall_at[f"group_recall_at_{k}"] = {
            "hit_count": len(group_hits),
            "truth_group_count": len(truth_group_ids),
            "recall": safe_div(len(group_hits), len(truth_group_ids)),
        }

    reciprocal_count = sum(1 for match in vector_matches if vector_reciprocal_rank(match) is not None and vector_reciprocal_rank(match) <= vector_top_k(match))
    known_negative_hits = [match_to_prediction_json(match) for match in vector_matches if match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number) in known_negatives]

    return {
        "summary": {
            "vector_candidate_count": len(vector_matches),
            "embedding_only_candidate_count": len(embedding_only),
            "vector_candidates_per_100_pages_estimate": None,
            "reciprocal_vector_candidate_count": reciprocal_count,
            "known_negative_vector_hit_count": len(known_negative_hits),
            "average_vector_margin": average([vector_margin_for_match(match) for match in vector_matches]),
            "average_vector_similarity": average([vector_similarity_for_match(match) for match in vector_matches]),
            **recall_at,
        },
        "by_source_relation": dict(count_vector_detail(vector_matches, "source_relation")),
        "by_visibility": dict(Counter(match.visibility for match in vector_matches)),
        "known_negative_vector_hits_preview": known_negative_hits[:100],
    }


def build_page_to_truth_groups(truth_pairs: list[TruthPair]) -> dict[tuple[str, int], set[str]]:
    mapping: dict[tuple[str, int], set[str]] = defaultdict(set)
    for pair in truth_pairs:
        group_id = pair.raw_metadata.get("truth_group_id")
        if not group_id:
            continue
        group = str(group_id)
        mapping[pair.a.key].add(group)
        mapping[pair.b.key].add(group)
    return mapping


def vector_truth_group_hits(
    vector_matches: list[PageMatch],
    page_to_truth_groups: dict[tuple[str, int], set[str]],
    k: int,
) -> set[str]:
    hits: set[str] = set()
    for match in vector_matches:
        if vector_rank_for_match(match) > k:
            continue
        left_groups = page_to_truth_groups.get(match.page_a.page_key, set())
        right_groups = page_to_truth_groups.get(match.page_b.page_key, set())
        hits.update(left_groups & right_groups)
    return hits


def build_review_queue_eval(matches: list[PageMatch], truth_pairs: list[TruthPair]) -> dict[str, Any]:
    truth_by_key = {pair.unordered_key: pair for pair in truth_pairs}
    duplicate_keys = {pair.unordered_key for pair in truth_pairs if pair.label == "duplicate"}
    negative_keys = {pair.unordered_key for pair in truth_pairs if pair.label == "not_duplicate"}
    by_visibility: dict[str, dict[str, Any]] = {}

    for visibility in sorted({match.visibility for match in matches} | {"main_review_list", "secondary_review", "calibration_only", "low_information"}):
        bucket = [match for match in matches if match.visibility == visibility]
        keys = {match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number) for match in bucket}
        by_visibility[visibility] = {
            "candidate_count": len(bucket),
            "duplicate_truth_hits": len(keys & duplicate_keys),
            "known_negative_hits": len(keys & negative_keys),
            "unknown_candidates": len([key for key in keys if key not in truth_by_key]),
            "duplicate_recall": safe_div(len(keys & duplicate_keys), len(duplicate_keys)),
        }

    any_keys = {match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number) for match in matches}
    return {
        "summary": {
            "candidate_count": len(matches),
            "main_review_candidate_count": by_visibility.get("main_review_list", {}).get("candidate_count", 0),
            "secondary_review_candidate_count": by_visibility.get("secondary_review", {}).get("candidate_count", 0),
            "calibration_only_candidate_count": by_visibility.get("calibration_only", {}).get("candidate_count", 0),
            "low_information_candidate_count": by_visibility.get("low_information", {}).get("candidate_count", 0),
            "must_match_coverage_any_queue": safe_div(len(any_keys & duplicate_keys), len(duplicate_keys)),
            "must_match_coverage_main_review": by_visibility.get("main_review_list", {}).get("duplicate_recall"),
            "must_match_coverage_secondary_review": by_visibility.get("secondary_review", {}).get("duplicate_recall"),
            "must_match_coverage_main_or_secondary": safe_div(
                len((keys_for_visibility(matches, "main_review_list") | keys_for_visibility(matches, "secondary_review")) & duplicate_keys),
                len(duplicate_keys),
            ),
        },
        "by_visibility": by_visibility,
        "by_engine_label": dict(Counter(match.engine_candidate_label for match in matches)),
        "by_match_type": dict(Counter(match.match_type for match in matches)),
    }



def keys_for_visibility(matches: list[PageMatch], visibility: str) -> set[tuple[tuple[str, int], tuple[str, int]]]:
    return {
        match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number)
        for match in matches
        if match.visibility == visibility
    }

def build_stage_delta_eval(matches: list[PageMatch], truth_pairs: list[TruthPair], threshold: float) -> dict[str, Any]:
    deterministic = [match for match in matches if not match_has_embedding_signal(match)]
    vector_added = [match for match in matches if match_has_vector_signal(match)]
    embedding_supported = [match for match in matches if match_has_embedding_signal(match) and not match_has_vector_signal(match)]
    return {
        "basis": "candidate-source approximation; exact pre/post stage snapshots are not persisted yet",
        "deterministic_without_embedding_signals": strict_pair_eval_summary(deterministic, truth_pairs, threshold),
        "embedding_supported_existing_candidates": strict_pair_eval_summary(embedding_supported, truth_pairs, threshold),
        "vector_recall_added_candidates": strict_pair_eval_summary(vector_added, truth_pairs, threshold),
        "final_all_candidates": strict_pair_eval_summary(matches, truth_pairs, threshold),
    }


def build_unknown_prediction_buckets(matches: list[PageMatch], truth_pairs: list[TruthPair]) -> dict[str, Any]:
    known_truth = {pair.unordered_key for pair in truth_pairs}
    unknown = [
        match for match in matches
        if match_key_from_pages(match.page_a.document_name, match.page_a.page_number, match.page_b.document_name, match.page_b.page_number) not in known_truth
    ]
    buckets = {
        "embedding_only": [match for match in unknown if match_is_embedding_only(match)],
        "embedding_supported": [match for match in unknown if match_has_embedding_signal(match) and not match_is_embedding_only(match)],
        "low_information": [match for match in unknown if match.visibility == "low_information"],
        "main_review": [match for match in unknown if match.visibility == "main_review_list"],
        "calibration_only": [match for match in unknown if match.visibility == "calibration_only"],
    }
    return {
        "summary": {name: len(items) for name, items in buckets.items()} | {"total_unknown_predictions": len(unknown)},
        "preview": {name: [match_to_prediction_json(match) for match in items[:25]] for name, items in buckets.items()},
    }


def match_has_embedding_signal(match: PageMatch) -> bool:
    return any(signal.name in {"embedding_similarity", "hybrid_vector_score"} for signal in match.signals)


def match_has_vector_signal(match: PageMatch) -> bool:
    for signal in match.signals:
        if signal.name == "embedding_similarity" and signal.details.get("embedding_mode") in {"vector_recall", "bounded_recall", "hybrid_vector_recall"}:
            return True
    return match.candidate_stage in {"vector_recall", "embedding_recall", "hybrid_vector_recall"} or match.match_type in {"embedding_similarity_candidate", "hybrid_vector_candidate"}


def match_is_embedding_only(match: PageMatch) -> bool:
    signal_names = {signal.name for signal in match.signals}
    return bool(signal_names) and signal_names <= {"embedding_similarity", "hybrid_vector_score"}


def vector_rank_for_match(match: PageMatch) -> int:
    ranks = [int(signal.details.get("query_rank", 999999)) for signal in match.signals if signal.name == "embedding_similarity"]
    return min(ranks) if ranks else 999999


def vector_reciprocal_rank(match: PageMatch) -> int | None:
    values = [signal.details.get("reciprocal_rank") for signal in match.signals if signal.name == "embedding_similarity"]
    numeric = [int(value) for value in values if isinstance(value, int)]
    return min(numeric) if numeric else None


def vector_top_k(match: PageMatch) -> int:
    values = [signal.details.get("top_k") for signal in match.signals if signal.name == "embedding_similarity"]
    numeric = [int(value) for value in values if isinstance(value, int)]
    return max(numeric) if numeric else 1


def vector_margin_for_match(match: PageMatch) -> float:
    values = [float(signal.details.get("margin_to_next", 0.0) or 0.0) for signal in match.signals if signal.name == "embedding_similarity"]
    return max(values) if values else 0.0


def vector_similarity_for_match(match: PageMatch) -> float:
    values = [signal.score for signal in match.signals if signal.name == "embedding_similarity"]
    return max(values) if values else 0.0


def count_vector_detail(matches: Iterable[PageMatch], key: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for match in matches:
        value = "unknown"
        for signal in match.signals:
            if signal.name == "embedding_similarity" and key in signal.details:
                value = str(signal.details.get(key) or "unknown")
                break
        counts[value] += 1
    return counts


def count_page_attr(pages: Iterable[PageRecord], attr: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for page in pages:
        value = getattr(page, attr, None) or "unknown"
        key = str(value).split(";")[0].strip() or "unknown"
        counts[key] += 1
    return counts


def average(values: list[float]) -> float | None:
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 4)
