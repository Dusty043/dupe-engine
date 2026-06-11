from __future__ import annotations

from dupe_engine.candidates import should_adjudicate_candidate, to_candidate_matches
from dupe_engine.config import EngineConfig
from dupe_engine.models import MatchSignal, PageMatch, PageRecord


def make_page(page_number: int) -> PageRecord:
    return PageRecord(group="T", document_id="doc", document_name="doc.pdf", page_number=page_number, image_path=f"p{page_number}.png")


def test_candidate_wrapper_preserves_detector_sources() -> None:
    match = PageMatch(
        match_type="weighted_text_duplicate",
        confidence=0.81,
        page_a=make_page(1),
        page_b=make_page(2),
        signals=[MatchSignal("tfidf_cosine_similarity", 0.81)],
    )
    candidates = to_candidate_matches([match], EngineConfig())
    assert len(candidates) == 1
    assert candidates[0].candidate_label == "weighted_text_duplicate"
    assert candidates[0].candidate_sources == ["tfidf_cosine_similarity"]
    assert candidates[0].engine_candidate_label == "needs_review"
    assert candidates[0].visibility == "main_review_list"


def test_adjudication_band_is_configurable() -> None:
    match = PageMatch(
        match_type="weighted_text_duplicate",
        confidence=0.81,
        page_a=make_page(1),
        page_b=make_page(2),
        signals=[MatchSignal("tfidf_cosine_similarity", 0.81)],
    )
    assert should_adjudicate_candidate(match, EngineConfig()) is False
    assert should_adjudicate_candidate(match, EngineConfig(enable_adjudicator=True)) is True
    assert should_adjudicate_candidate(match, EngineConfig(enable_adjudicator=True, adjudicator_min_confidence=0.90)) is False
