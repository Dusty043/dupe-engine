from __future__ import annotations

from dupe_engine.config import EngineConfig
from dupe_engine.matchers import make_escalation_decision, stage_from_pass_records, text_pass_records, visual_pass_records
from dupe_engine.models import MatchSignal, PageMatch, PageRecord


def make_page(page_number: int) -> PageRecord:
    return PageRecord(group="T", document_id="doc", document_name="doc.pdf", page_number=page_number, image_path=f"p{page_number}.png")


def test_visual_pass_bands_are_not_independent_votes() -> None:
    config = EngineConfig(strict_phash_threshold=8, standard_phash_threshold=16, loose_phash_threshold=28)
    records = visual_pass_records(24, config)
    assert [record.matched for record in records] == [False, False, True]
    assert stage_from_pass_records(records) == "deterministic_loose"


def test_text_pass_bands_promote_to_standard() -> None:
    config = EngineConfig(strict_tfidf_threshold=0.94, standard_tfidf_threshold=0.86, loose_tfidf_threshold=0.74)
    records = text_pass_records(0.88, config)
    assert [record.matched for record in records] == [False, True, True]
    assert stage_from_pass_records(records) == "deterministic_standard"


def test_non_exact_standard_candidate_recommends_embedding_escalation() -> None:
    config = EngineConfig()
    records = text_pass_records(0.88, config)
    match = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.88,
        page_a=make_page(1),
        page_b=make_page(2),
        signals=[MatchSignal("tfidf_cosine_similarity", 0.88)],
        candidate_stage=stage_from_pass_records(records),
        deterministic_passes=records,
    )
    decision = make_escalation_decision(match, config)
    assert decision.embedding_required is True
    assert decision.llm_detector_required is False


def test_multipass_text_returns_empty_when_vectorizer_prunes_all_terms() -> None:
    from dupe_engine.config import EngineConfig
    from dupe_engine.matchers import multipass_text_matches
    from dupe_engine.models import PageRecord

    config = EngineConfig(tfidf_max_df=0.5)
    pages = []
    for idx in range(2):
        text = "same repeated clinical words medication assessment plan"
        page = PageRecord(
            group="A",
            document_id=f"doc{idx}",
            document_name=f"doc{idx}.pdf",
            page_number=1,
            image_path="/tmp/page.png",
            raw_text=text,
            best_text=text,
            comparison_text=text,
        )
        pages.append(page)

    assert multipass_text_matches(pages, pages, config) == []
