from __future__ import annotations

import math
from typing import Protocol


class ReviewableMatch(Protocol):
    match_type: str
    confidence: float
    candidate_stage: str
    page_a: object
    page_b: object
    signals: list
    review_bucket: str
    review_priority: str
    review_rationale: str
    engine_candidate_label: str
    adjudicator_suggested_label: str | None
    human_final_label: str | None
    visibility: str
    visibility_reason: str
    candidate_category: str


EXACT_SIGNAL_NAMES = {"exact_image_hash", "exact_normalized_text_hash"}
VISUAL_SIGNAL_NAMES = {"perceptual_hash"}
TEXT_SIGNAL_NAMES = {"tfidf_cosine_similarity", "embedding_similarity", "hybrid_vector_score"}

# Reviewer-facing labels accepted by the v1 goalpost. low_information_ignore is
# intentionally not here; it is a truth/evaluation category and a visibility
# route, not a duplicate-status label.
ENGINE_CANDIDATE_LABELS = {
    "duplicate",
    "likely_duplicate",
    "possible_duplicate",
    "partial_overlap",
    "needs_review",
}
ADJUDICATOR_SUGGESTED_LABELS = ENGINE_CANDIDATE_LABELS | {"not_duplicate"}
HUMAN_FINAL_LABELS = ADJUDICATOR_SUGGESTED_LABELS

# Backwards-compatible name used by existing reports/tests.
REVIEW_BUCKETS = ENGINE_CANDIDATE_LABELS

VISIBILITY_BUCKETS = {
    "main_review_list",
    "secondary_review",
    "low_information",
    "calibration_only",
}

DEFAULT_MAIN_REVIEW_MIN_CONFIDENCE = 0.86


def annotate_match_for_review(
    match: ReviewableMatch,
    main_review_min_confidence: float = DEFAULT_MAIN_REVIEW_MIN_CONFIDENCE,
    queue_profile: str = "balanced",
) -> ReviewableMatch:
    """Attach v1-shaped reviewer metadata to a detector match.

    The engine label is not a human final decision. It is the candidate label
    shown in the queue before adjudicator or reviewer action. Low-information
    handling is expressed through visibility so blank/cover/separator pages can
    be hidden from the main list without inventing a fake duplicate label.
    """

    label, priority, rationale, visibility, visibility_reason, category = classify_review_bucket(
        match,
        main_review_min_confidence=main_review_min_confidence,
        queue_profile=queue_profile,
    )
    match.engine_candidate_label = label
    match.review_bucket = label  # legacy alias retained for v0.7/v0.8 consumers
    match.review_priority = priority
    match.review_rationale = rationale
    match.visibility = visibility
    match.visibility_reason = visibility_reason
    match.candidate_category = category
    if not hasattr(match, "adjudicator_suggested_label"):
        match.adjudicator_suggested_label = None
    if not hasattr(match, "human_final_label"):
        match.human_final_label = None
    return match


def classify_review_bucket(
    match: ReviewableMatch,
    main_review_min_confidence: float = DEFAULT_MAIN_REVIEW_MIN_CONFIDENCE,
    queue_profile: str = "balanced",
) -> tuple[str, str, str, str, str, str]:
    signal_names = {getattr(signal, "name", "") for signal in match.signals}
    low_info = bool(getattr(match.page_a, "is_low_information", False) or getattr(match.page_b, "is_low_information", False))
    exact = bool(EXACT_SIGNAL_NAMES & signal_names or match.candidate_stage == "deterministic_exact")
    has_text = bool(TEXT_SIGNAL_NAMES & signal_names)
    has_visual = bool(VISUAL_SIGNAL_NAMES & signal_names)
    multi_signal = len(signal_names) > 1 or (has_text and has_visual)

    visibility = "main_review_list"
    visibility_reason = "candidate has enough non-low-information evidence for the main review list"
    category = "standard"

    if low_info:
        visibility = "low_information"
        visibility_reason = "one or both pages are low-information; hide from the main review list and show in a separate section"
        category = "low_information"
        if exact:
            return (
                "duplicate",
                "low",
                "exact hash matched, but the pair is low-information and should be reviewed separately from the main list",
                visibility,
                visibility_reason,
                category,
            )
        return (
            "needs_review",
            "low",
            "low-information pair retained only for separate review/sampling, not as a main duplicate candidate",
            visibility,
            visibility_reason,
            category,
        )

    if exact:
        return (
            "duplicate",
            "high",
            "exact image/text hash matched; deterministic evidence is strong enough for duplicate review queue",
            visibility,
            visibility_reason,
            category,
        )

    if match.candidate_stage == "deterministic_strict":
        if multi_signal or match.confidence >= 0.90:
            return (
                "likely_duplicate",
                "high",
                "strict deterministic pass with strong confidence or multiple supporting signals",
                visibility,
                visibility_reason,
                category,
            )
        return (
            "possible_duplicate",
            "medium",
            "strict deterministic pass, but evidence is single-signal or lower confidence",
            visibility,
            visibility_reason,
            category,
        )

    if match.confidence >= 0.94 and multi_signal:
        return (
            "likely_duplicate",
            "high",
            "very high confidence with multiple detector signals",
            visibility,
            visibility_reason,
            category,
        )

    if match.candidate_stage in {"embedding_recall", "vector_recall", "hybrid_vector_recall"} and signal_names <= {"embedding_similarity", "hybrid_vector_score"}:
        queue_profile = normalize_queue_profile(queue_profile)
        secondary_threshold = embedding_secondary_threshold(queue_profile, main_review_min_confidence)
        if match.confidence >= secondary_threshold:
            return (
                "possible_duplicate",
                "medium" if queue_profile != "strict_main" else "low",
                "embedding-only vector recall candidate; route to secondary review before any duplicate decision",
                "secondary_review",
                f"embedding-only candidate met {queue_profile} secondary recall threshold; keep out of default main review",
                "semantic_recall",
            )
        return (
            "needs_review",
            "low",
            "embedding-only vector recall candidate below secondary recall threshold; retained for calibration",
            "calibration_only",
            "embedding-only candidate is below the selected secondary-review threshold",
            "semantic_recall",
        )

    if match.candidate_stage == "deterministic_standard" or match.confidence >= main_review_min_confidence:
        return (
            "possible_duplicate",
            "medium",
            "standard-band deterministic candidate; useful for recall but should be reviewed before duplicate decision",
            visibility,
            visibility_reason,
            category,
        )

    if match.candidate_stage == "deterministic_loose" or match.confidence >= 0.60:
        return (
            "needs_review",
            "low",
            "loose or borderline deterministic candidate retained for calibration; hidden from the default main review list",
            "calibration_only",
            "candidate is below the default main-list confidence band; keep in calibration artifacts but hide from the reviewer queue by default",
            "standard",
        )

    return (
        "needs_review",
        "low",
        "weak candidate retained for diagnostics rather than duplicate action",
        "calibration_only",
        "candidate is below the default main-list confidence band; keep in calibration artifacts only",
        "standard",
    )


def priority_rank(priority: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(priority, 0)


def visibility_rank(visibility: str) -> int:
    return {"main_review_list": 4, "secondary_review": 3, "low_information": 2, "calibration_only": 1}.get(visibility, 0)


def normalize_queue_profile(value: str) -> str:
    normalized = (value or "balanced").strip().lower().replace("-", "_")
    return normalized if normalized in {"strict_main", "balanced", "recall_first"} else "balanced"


def embedding_secondary_threshold(queue_profile: str, main_review_min_confidence: float) -> float:
    profile = normalize_queue_profile(queue_profile)
    if profile == "strict_main":
        return max(0.92, main_review_min_confidence + 0.04)
    if profile == "recall_first":
        return min(0.82, main_review_min_confidence)
    return max(0.86, main_review_min_confidence)


def apply_main_review_visibility_budget(
    matches: list[ReviewableMatch],
    total_pages: int,
    max_candidates_per_100_pages: int = 50,
) -> list[ReviewableMatch]:
    """Route main-list overflow to calibration-only visibility.

    This does not delete detector candidates. It only marks which candidates
    belong in the default reviewer queue versus calibration output. Exact
    duplicates stay protected in the main list even if the queue is otherwise
    full.
    """

    if total_pages <= 0 or max_candidates_per_100_pages <= 0:
        return matches

    budget = max(1, math.ceil(total_pages * max_candidates_per_100_pages / 100))
    main_candidates = [match for match in matches if match.visibility == "main_review_list"]
    if len(main_candidates) <= budget:
        return matches

    protected = [match for match in main_candidates if match.engine_candidate_label == "duplicate"]
    remaining_budget = max(0, budget - len(protected))
    ranked = [match for match in main_candidates if match.engine_candidate_label != "duplicate"]
    ranked.sort(key=main_review_budget_sort_key, reverse=True)
    keep_ids = {id(match) for match in protected + ranked[:remaining_budget]}

    for match in main_candidates:
        if id(match) in keep_ids:
            continue
        match.visibility = "calibration_only"
        match.visibility_reason = (
            f"candidate exceeded default main-review budget of {budget} for {total_pages} pages; "
            "retained in calibration outputs"
        )
        match.candidate_category = "budget_overflow"
        if hasattr(match, "recommendation"):
            match.recommendation = "hide_from_main_list_keep_for_calibration"
    return matches


def main_review_budget_sort_key(match: ReviewableMatch) -> tuple[int, int, float, int]:
    label_rank = {
        "duplicate": 5,
        "likely_duplicate": 4,
        "possible_duplicate": 3,
        "partial_overlap": 2,
        "needs_review": 1,
    }.get(match.engine_candidate_label, 0)
    signal_count = len({getattr(signal, "name", "") for signal in match.signals})
    return (label_rank, priority_rank(match.review_priority), float(match.confidence), signal_count)
