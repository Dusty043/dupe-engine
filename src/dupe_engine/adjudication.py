from __future__ import annotations

from .config import EngineConfig
from .models import AdjudicatedMatch, AdjudicationResult, CandidateMatch


ALLOWED_ADJUDICATION_DECISIONS = {
    "duplicate",
    "likely_duplicate",
    "possible_duplicate",
    "partial_overlap",
    "not_duplicate",
    "needs_review",
    "not_run",
}


def noop_adjudicate(candidate: CandidateMatch, config: EngineConfig) -> AdjudicatedMatch:
    """Return a non-invasive adjudication placeholder.

    Real LLM adjudication will be added after candidate calibration. This object
    lets reports and downstream UI plan for the future schema now.
    """

    reason = "adjudicator disabled or not integrated; candidate uses detector score only"
    decision = "not_run"
    return AdjudicatedMatch(
        candidate=candidate,
        adjudication=AdjudicationResult(
            decision=decision,
            confidence=0.0,
            reason=reason,
            provider=config.adjudicator_provider,
            model=config.adjudicator_model or None,
        ),
        final_label=candidate.engine_candidate_label,
        final_confidence=candidate.candidate_score,
        human_recommendation="review",
    )


def noop_adjudicate_many(candidates: list[CandidateMatch], config: EngineConfig) -> list[AdjudicatedMatch]:
    return [noop_adjudicate(candidate, config) for candidate in candidates]
