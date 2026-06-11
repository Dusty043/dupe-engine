from __future__ import annotations

from dupe_engine.calibration import build_calibration_report, parse_thresholds
from dupe_engine.config import EngineConfig
from dupe_engine.evaluation import load_truth_pairs
from dupe_engine.matchers import apply_candidate_controls, text_pass_records
from dupe_engine.models import MatchSignal, PageMatch, PageRecord, TruthPageRef, TruthPair
from dupe_engine.review import annotate_match_for_review, apply_main_review_visibility_budget


def make_page(document: str, page_number: int, text: str = "clinical note medication assessment plan") -> PageRecord:
    return PageRecord(
        group="T",
        document_id=document.replace(".", "_"),
        document_name=document,
        page_number=page_number,
        image_path=f"{document}-{page_number}.png",
        raw_text=text,
        best_text=text,
        comparison_text=text,
        best_word_count=len(text.split()),
    )


def test_exact_match_gets_duplicate_review_bucket() -> None:
    match = PageMatch(
        match_type="exact_text_duplicate",
        confidence=0.99,
        page_a=make_page("a.pdf", 1),
        page_b=make_page("b.pdf", 1),
        signals=[MatchSignal("exact_normalized_text_hash", 1.0)],
        candidate_stage="deterministic_exact",
    )
    annotate_match_for_review(match)
    assert match.review_bucket == "duplicate"
    assert match.review_priority == "high"


def test_standard_text_match_gets_possible_duplicate_bucket() -> None:
    config = EngineConfig()
    records = text_pass_records(0.88, config)
    match = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.88,
        page_a=make_page("a.pdf", 1),
        page_b=make_page("b.pdf", 1),
        signals=[MatchSignal("tfidf_cosine_similarity", 0.88)],
        candidate_stage="deterministic_standard",
        deterministic_passes=records,
    )
    kept = apply_candidate_controls([match], config)
    assert kept[0].review_bucket == "possible_duplicate"
    assert kept[0].engine_candidate_label == "possible_duplicate"
    assert kept[0].visibility == "main_review_list"


def test_low_information_is_visibility_not_review_label() -> None:
    page_a = make_page("a.pdf", 1)
    page_b = make_page("b.pdf", 1)
    page_a.is_low_information = True
    page_a.low_information_reason = "blank_page"
    match = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.91,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("tfidf_cosine_similarity", 0.91)],
        candidate_stage="deterministic_strict",
    )
    annotate_match_for_review(match)
    assert match.engine_candidate_label == "needs_review"
    assert match.review_bucket == "needs_review"
    assert match.visibility == "low_information"
    assert match.candidate_category == "low_information"


def test_loose_candidate_defaults_to_calibration_only_visibility() -> None:
    match = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.75,
        page_a=make_page("a.pdf", 1),
        page_b=make_page("b.pdf", 1),
        signals=[MatchSignal("tfidf_cosine_similarity", 0.75)],
        candidate_stage="deterministic_loose",
    )
    annotate_match_for_review(match)
    assert match.engine_candidate_label == "needs_review"
    assert match.visibility == "calibration_only"


def test_main_review_visibility_budget_keeps_overflow_for_calibration() -> None:
    matches = []
    for idx in range(1, 5):
        match = PageMatch(
            match_type="weighted_text_candidate",
            confidence=0.95 - idx / 100,
            page_a=make_page("a.pdf", idx),
            page_b=make_page("b.pdf", idx),
            signals=[MatchSignal("tfidf_cosine_similarity", 0.95 - idx / 100)],
            candidate_stage="deterministic_strict",
        )
        annotate_match_for_review(match)
        matches.append(match)

    apply_main_review_visibility_budget(matches, total_pages=4, max_candidates_per_100_pages=50)
    assert sum(1 for match in matches if match.visibility == "main_review_list") == 2
    assert sum(1 for match in matches if match.visibility == "calibration_only") == 2


def test_calibration_report_splits_false_negative_and_known_negative() -> None:
    page_a = make_page("a.pdf", 1)
    page_b = make_page("b.pdf", 1)
    page_c = make_page("c.pdf", 1)
    predicted_known_negative = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.91,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal("tfidf_cosine_similarity", 0.91)],
        candidate_stage="deterministic_strict",
    )
    truth_pairs = [
        TruthPair(TruthPageRef("a.pdf", 1), TruthPageRef("b.pdf", 1), label="not_duplicate", kind="hard_negative"),
        TruthPair(TruthPageRef("a.pdf", 1), TruthPageRef("c.pdf", 1), label="duplicate", kind="must_match"),
    ]
    report = build_calibration_report([predicted_known_negative], truth_pairs, pages=[page_a, page_b, page_c])
    assert report["summary"]["false_positive_issue_counts"]["known_negative_hit"] == 1
    assert report["summary"]["false_negative_review_count"] == 1
    assert report["summary"]["main_review_list_candidate_count"] == 1
    assert report["candidate_summary"][0]["engine_candidate_label"] == "likely_duplicate"
    assert report["candidate_summary"][0]["visibility"] == "main_review_list"
    assert report["threshold_sweep"]


def test_parse_thresholds_validates_range() -> None:
    assert parse_thresholds("0.5,0.9,0.5") == [0.5, 0.9]
    try:
        parse_thresholds("1.5")
    except ValueError as exc:
        assert "between 0 and 1" in str(exc)
    else:
        raise AssertionError("expected ValueError")
