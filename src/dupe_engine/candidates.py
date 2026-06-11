from __future__ import annotations

from .config import EngineConfig
from .models import CandidateMatch, PageMatch


def should_adjudicate_candidate(match: PageMatch, config: EngineConfig) -> bool:
    """Return whether a candidate is in the intended adjudication band."""

    if match.escalation.adjudicator_required:
        return True
    if not config.enable_adjudicator:
        return False
    if not config.adjudicator_borderline_only:
        return True
    return config.adjudicator_min_confidence <= match.confidence <= config.adjudicator_max_confidence


def to_candidate_matches(matches: list[PageMatch], config: EngineConfig) -> list[CandidateMatch]:
    return [CandidateMatch.from_page_match(match, needs_adjudication=should_adjudicate_candidate(match, config)) for match in matches]


def summarize_candidates(candidates: list[CandidateMatch]) -> dict[str, object]:
    source_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    review_bucket_counts: dict[str, int] = {}
    review_priority_counts: dict[str, int] = {}
    engine_label_counts: dict[str, int] = {}
    visibility_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    adjudication_needed = 0
    embedding_escalation = 0
    llm_detector_escalation = 0

    for candidate in candidates:
        stage_counts[candidate.candidate_stage] = stage_counts.get(candidate.candidate_stage, 0) + 1
        review_bucket_counts[candidate.review_bucket] = review_bucket_counts.get(candidate.review_bucket, 0) + 1
        review_priority_counts[candidate.review_priority] = review_priority_counts.get(candidate.review_priority, 0) + 1
        engine_label_counts[candidate.engine_candidate_label] = engine_label_counts.get(candidate.engine_candidate_label, 0) + 1
        visibility_counts[candidate.visibility] = visibility_counts.get(candidate.visibility, 0) + 1
        category_counts[candidate.candidate_category] = category_counts.get(candidate.candidate_category, 0) + 1
        if candidate.needs_adjudication:
            adjudication_needed += 1
        if candidate.escalation.embedding_required:
            embedding_escalation += 1
        if candidate.escalation.llm_detector_required:
            llm_detector_escalation += 1
        for source in candidate.candidate_sources:
            source_counts[source] = source_counts.get(source, 0) + 1

    return {
        "candidate_count": len(candidates),
        "main_review_list_candidate_count": visibility_counts.get("main_review_list", 0),
        "low_information_candidate_count": visibility_counts.get("low_information", 0),
        "calibration_only_candidate_count": visibility_counts.get("calibration_only", 0),
        "candidate_source_counts": source_counts,
        "candidate_stage_counts": stage_counts,
        "engine_candidate_label_counts": engine_label_counts,
        "review_bucket_counts": review_bucket_counts,
        "review_priority_counts": review_priority_counts,
        "candidate_visibility_counts": visibility_counts,
        "candidate_category_counts": category_counts,
        "embedding_escalation_recommended_count": embedding_escalation,
        "llm_detector_escalation_recommended_count": llm_detector_escalation,
        "adjudication_needed_count": adjudication_needed,
    }
