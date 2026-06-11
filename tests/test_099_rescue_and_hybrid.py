from __future__ import annotations

from dupe_engine.calibration_harness import build_initial_plan
from dupe_engine.config import EngineConfig
from dupe_engine.embedding_detector import vector_gate_decision
from dupe_engine.models import MatchSignal, PageMatch, PageRecord
from dupe_engine.ocr import select_post_candidate_openai_ocr_pages


def make_page(page_id: int, *, words: int = 0, text: str = "") -> PageRecord:
    page = PageRecord(
        group="A" if page_id < 100 else "B",
        document_id=f"doc_{page_id}",
        document_name=f"doc_{page_id}.pdf",
        page_number=1,
        image_path=f"/tmp/page_{page_id}.png",
        raw_text=text,
        best_text=text,
        best_word_count=words or len(text.split()),
        native_text_status="missing" if not text else "weak",
        best_text_source="none" if not text else "native",
    )
    page.tesseract_attempted = True
    page.tesseract_usable = False
    page.ocr_route = "tesseract_weak"
    return page


def test_focused_rescue_plan_is_five_runs_with_hybrid_tests() -> None:
    plan = build_initial_plan("focused_rescue", ["control", "ocr", "vector", "queue"], max_runs=None)

    assert len(plan) == 5
    assert plan[0].vector_profile == "conservative"
    assert any(spec.post_candidate_rescue_pages == 50 and spec.vector_profile == "conservative" for spec in plan)
    assert any(spec.post_candidate_rescue_pages == 75 and spec.embedding_hybrid_scoring for spec in plan)


def test_post_candidate_rescue_selects_remaining_weak_candidate_pages() -> None:
    left = make_page(1)
    right = make_page(101)
    match = PageMatch(
        match_type="embedding_similarity_candidate",
        confidence=0.72,
        page_a=left,
        page_b=right,
        signals=[MatchSignal("embedding_similarity", 0.9, {"embedding_mode": "vector_recall"})],
        candidate_stage="vector_recall",
    )
    config = EngineConfig(
        openai_ocr_post_candidate_rescue_enabled=True,
        openai_ocr_post_candidate_max_pages=1,
        openai_ocr_post_candidate_min_confidence=0.5,
        openai_ocr_max_pages_per_document=5,
    )

    selected = select_post_candidate_openai_ocr_pages([match], config, pages=[left, right])

    assert len(selected) == 1
    assert selected[0][1].startswith("post_candidate_rescue selection")


def test_hybrid_vector_gate_can_accept_supported_lower_similarity() -> None:
    left = make_page(1, text="claimant treatment plan follow up provider assessment notes repeated details")
    right = make_page(101, text="patient treatment plan followup provider assessment details repeated notes")
    config = EngineConfig(
        embeddings_similarity_threshold=0.88,
        embeddings_min_margin=0.03,
        embeddings_hybrid_scoring_enabled=True,
        embeddings_hybrid_min_score=0.70,
    )

    gate = vector_gate_decision(
        score=0.84,
        margin=0.02,
        reciprocal_ok=True,
        cross_source=True,
        config=config,
        page_a=left,
        page_b=right,
        query_rank=1,
        reciprocal_rank=1,
    )

    assert gate["accepted"] is True
    assert gate["hybrid_scoring_enabled"] is True
    assert gate["hybrid"]["score"] >= 0.70
