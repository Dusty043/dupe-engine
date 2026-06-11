from __future__ import annotations

from dupe_engine.config import EngineConfig
from dupe_engine.embedding_detector import vector_gate_decision
from dupe_engine.models import MatchSignal, PageMatch, PageRecord, TruthPageRef, TruthPair
from dupe_engine.phase_eval import build_phase_eval_report


def make_page(group: str, doc: str, page: int, text: str = "usable clinical assessment treatment plan") -> PageRecord:
    return PageRecord(
        group=group,
        document_id=doc,
        document_name=f"{group}/{doc}.pdf",
        page_number=page,
        image_path=f"/tmp/{doc}_{page}.png",
        raw_text=text,
        best_text=text,
        comparison_text=text,
        best_text_source="openai_ocr",
        best_word_count=len(text.split()),
        native_text_status="weak",
        openai_ocr_selected=True,
        openai_ocr_attempted=True,
        openai_ocr_usable=True,
        ocr_route="openai_ocr_fallback",
    )


def test_vector_gate_requires_margin_unless_reciprocal() -> None:
    config = EngineConfig(embeddings_similarity_threshold=0.88, embeddings_min_margin=0.03)

    rejected = vector_gate_decision(score=0.91, margin=0.01, reciprocal_ok=False, cross_source=True, config=config)
    accepted = vector_gate_decision(score=0.91, margin=0.01, reciprocal_ok=True, cross_source=True, config=config)

    assert rejected["accepted"] is False
    assert "low_margin_not_reciprocal" in rejected["reasons"]
    assert accepted["accepted"] is True


def test_phase_eval_separates_vector_retrieval_from_strict_eval() -> None:
    left = make_page("source_A", "received", 1)
    right = make_page("source_B", "ere", 1)
    match = PageMatch(
        match_type="embedding_similarity_candidate",
        confidence=0.92,
        page_a=left,
        page_b=right,
        candidate_stage="vector_recall",
        signals=[
            MatchSignal(
                "embedding_similarity",
                0.92,
                {
                    "embedding_mode": "vector_recall",
                    "query_rank": 1,
                    "reciprocal_rank": 1,
                    "top_k": 5,
                    "margin_to_next": 0.08,
                    "source_relation": "cross_source",
                },
            )
        ],
    )
    truth = TruthPair(
        a=TruthPageRef(document=left.document_name, page=1),
        b=TruthPageRef(document=right.document_name, page=1),
        label="duplicate",
        expected_min_layer="embedding",
    )

    report = build_phase_eval_report([left, right], [match], [truth])

    assert report["strict_pair_eval"]["true_positive_count"] == 1
    assert report["ocr_rescue_eval"]["summary"]["ocr_ready_pair_rate"] == 1.0
    assert report["vector_retrieval_eval"]["summary"]["vector_candidate_count"] == 1
    assert report["vector_retrieval_eval"]["summary"]["recall_at_1"]["recall"] == 1.0
    assert report["review_queue_eval"]["summary"]["must_match_coverage_any_queue"] == 1.0
