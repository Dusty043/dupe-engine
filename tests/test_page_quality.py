from __future__ import annotations

from dupe_engine.config import EngineConfig
from dupe_engine.matchers import apply_candidate_controls
from dupe_engine.models import MatchSignal, PageMatch, PageRecord
from dupe_engine.page_quality import annotate_page_quality


def make_page(page_number: int, text: str) -> PageRecord:
    return PageRecord(
        group="T",
        document_id="doc",
        document_name="doc.pdf",
        page_number=page_number,
        image_path=f"p{page_number}.png",
        raw_text=text,
        best_text=text,
        comparison_text=text,
        best_word_count=len(text.split()),
    )


def test_low_information_page_is_annotated() -> None:
    page = make_page(1, "Intentionally left blank")
    annotate_page_quality(page, EngineConfig())
    assert page.is_low_information is True
    assert page.low_information_reason is not None


def test_low_information_candidate_is_suppressed() -> None:
    config = EngineConfig()
    page_a = make_page(1, "Intentionally left blank")
    page_b = make_page(2, "Intentionally left blank")
    annotate_page_quality(page_a, config)
    annotate_page_quality(page_b, config)
    match = PageMatch(
        match_type="exact_text_duplicate",
        confidence=0.99,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("exact_normalized_text_hash", 1.0)],
    )
    assert apply_candidate_controls([match], config) == []


def test_candidate_budget_limits_per_page() -> None:
    config = EngineConfig(max_candidates_per_page=1, max_candidates_per_job=10, suppress_low_information_candidates=False)
    anchor = make_page(1, "meaningful clinical page text with lumbar medication assessment plan")
    others = [make_page(i, f"meaningful clinical page text {i} lumbar medication assessment plan") for i in range(2, 5)]
    matches = [
        PageMatch(
            match_type="weighted_text_candidate",
            confidence=0.90 - i * 0.01,
            page_a=anchor,
            page_b=page,
            signals=[MatchSignal("tfidf_cosine_similarity", 0.90 - i * 0.01)],
        )
        for i, page in enumerate(others)
    ]
    kept = apply_candidate_controls(matches, config)
    assert len(kept) == 1
