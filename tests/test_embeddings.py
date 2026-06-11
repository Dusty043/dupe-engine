from __future__ import annotations

from dupe_engine.capabilities import build_capability_report
from dupe_engine.config import EngineConfig
from dupe_engine.embedding_detector import cosine_similarity, select_embedding_candidates
from dupe_engine.models import EscalationDecision, MatchSignal, PageMatch, PageRecord


def make_page(page_number: int) -> PageRecord:
    return PageRecord(
        group="T",
        document_id="doc",
        document_name="doc.pdf",
        page_number=page_number,
        image_path=f"p{page_number}.png",
        raw_text="meaningful clinical note with medication diagnosis assessment plan",
        best_text="meaningful clinical note with medication diagnosis assessment plan",
        comparison_text="meaningful clinical note with medication diagnosis assessment plan",
    )


def test_cosine_similarity_basic() -> None:
    assert cosine_similarity([1, 0], [1, 0]) == 1.0
    assert cosine_similarity([1, 0], [0, 1]) == 0.0


def test_embedding_status_available_with_openai_key(monkeypatch) -> None:
    monkeypatch.setenv("DUPE_OPENAI_API_KEY", "test-key")
    report = build_capability_report(EngineConfig(enable_embeddings=True, embeddings_provider="openai"))
    status = report.layers["embeddings"]
    assert status.enabled is True
    assert status.available is True
    assert status.status == "available"


def test_embedding_candidate_selection_skips_exact_and_uses_escalation() -> None:
    config = EngineConfig()
    escalated = PageMatch(
        match_type="weighted_text_candidate",
        confidence=0.82,
        page_a=make_page(1),
        page_b=make_page(2),
        signals=[MatchSignal("tfidf_cosine_similarity", 0.82)],
        escalation=EscalationDecision(embedding_required=True),
    )
    exact = PageMatch(
        match_type="exact_text_duplicate",
        confidence=0.99,
        page_a=make_page(3),
        page_b=make_page(4),
        signals=[MatchSignal("exact_normalized_text_hash", 1.0)],
        escalation=EscalationDecision(embedding_required=False),
    )
    selected = select_embedding_candidates([exact, escalated], config)
    assert selected == [escalated]
