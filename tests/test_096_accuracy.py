from __future__ import annotations

from pathlib import Path

from dupe_engine.capabilities import ProviderStatus
from dupe_engine.config import EngineConfig
from dupe_engine.embedding_detector import apply_embedding_detector
from dupe_engine.models import MatchSignal, PageMatch, PageRecord
from dupe_engine.ocr import select_openai_ocr_pages, should_accept_openai_ocr_result


def make_page(page_id: int, text: str = "") -> PageRecord:
    return PageRecord(
        group="A" if page_id < 100 else "B",
        document_id=f"doc_{page_id}",
        document_name=f"doc_{page_id}.pdf",
        page_number=1,
        image_path=f"/tmp/page_{page_id}.png",
        native_text=text,
        raw_text=text,
        best_text=text,
        comparison_text=text,
        best_text_source="native" if text else "none",
        best_word_count=len(text.split()),
        native_text_status="weak" if text else "missing",
    )


def test_openai_ocr_accepts_shorter_cleaner_usable_text() -> None:
    noisy = " ".join(["ZXCVBNM1234567890"] * 12)
    clean = "claimant hearing notice appointment followup assessment plan treatment provider diagnosis medication therapy"
    page = make_page(1, noisy)
    page.native_text_status = "weak"
    config = EngineConfig(native_min_usable_words=8, tesseract_min_words=8)

    accepted, reason, quality = should_accept_openai_ocr_result(page, clean, config)

    assert accepted is True
    assert reason in {"openai_ocr_cleaner_usable_text", "openai_ocr_shorter_but_cleaner_text"}
    assert quality["candidate_quality"] > quality["current_quality"]
    assert len(clean) < len(noisy)


def test_ocr_rescue_selection_prioritizes_real_weak_pages_over_low_information() -> None:
    config = EngineConfig(openai_ocr_max_pages_per_job=1, openai_ocr_selection_mode="weak_pages")
    weak = make_page(1)
    weak.native_text_status = "missing"
    weak.ocr_route = "tesseract_weak"
    weak.tesseract_attempted = True
    weak.tesseract_usable = False
    weak.best_word_count = 20

    low_info = make_page(2)
    low_info.native_text_status = "missing"
    low_info.ocr_route = "tesseract_weak"
    low_info.tesseract_attempted = True
    low_info.tesseract_usable = False
    low_info.best_word_count = 0
    low_info.is_low_information = True
    low_info.low_information_reason = "blank_or_separator"

    selected = select_openai_ocr_pages([], config, pages=[low_info, weak])

    assert selected == [(weak, selected[0][1])]


class FakeEmbeddingProvider:
    def embed_texts(self, texts: list[str]):
        vectors = []
        for text in texts:
            lower = text.lower()
            if "two weeks" in lower or "14 days" in lower:
                vectors.append([1.0, 0.0])
            else:
                vectors.append([0.0, 1.0])
        return type("EmbeddingResultLike", (), {"vectors": vectors, "provider": "openai", "model": "fake-embedding", "metadata": {"fake": True}})()


def available_embedding_status(config: EngineConfig) -> ProviderStatus:
    return ProviderStatus(
        layer="embeddings",
        enabled=True,
        available=True,
        provider="openai",
        status="available",
        model="fake-embedding",
    )


def test_embedding_recall_creates_new_candidate_pair(monkeypatch) -> None:
    import dupe_engine.embedding_detector as module

    monkeypatch.setattr(module, "check_embeddings_status", available_embedding_status)
    monkeypatch.setattr(module, "make_embedding_provider", lambda config: FakeEmbeddingProvider())

    config = EngineConfig(
        enable_embeddings=True,
        embeddings_similarity_threshold=0.90,
        embeddings_candidate_top_k=1,
        embeddings_min_words=3,
        embeddings_min_text_chars=20,
        max_embedding_pairs_per_job=10,
    )
    received = make_page(1, "claimant advised to remain off work for two weeks after injury")
    ere_match = make_page(101, "doctor says patient was unable to work for 14 days after accident")
    unrelated = make_page(102, "benefit letter states hearing date and office contact information")

    matches = apply_embedding_detector([], config, pages_a=[received], pages_b=[ere_match, unrelated])

    assert len(matches) == 1
    assert matches[0].match_type == "embedding_similarity_candidate"
    assert matches[0].page_a is received
    assert matches[0].page_b is ere_match
    assert matches[0].engine_candidate_label in {"possible_duplicate", "needs_review"}
    assert matches[0].ai_route_events[0]["changed_matching"] is True


def test_embedding_recall_does_not_duplicate_existing_exact_pair(monkeypatch) -> None:
    import dupe_engine.embedding_detector as module

    monkeypatch.setattr(module, "check_embeddings_status", available_embedding_status)
    monkeypatch.setattr(module, "make_embedding_provider", lambda config: FakeEmbeddingProvider())

    config = EngineConfig(
        enable_embeddings=True,
        embeddings_similarity_threshold=0.90,
        embeddings_candidate_top_k=1,
        embeddings_min_words=3,
        embeddings_min_text_chars=20,
        max_embedding_pairs_per_job=10,
    )
    left = make_page(1, "claimant advised to remain off work for two weeks after injury")
    right = make_page(101, "doctor says patient was unable to work for 14 days after accident")
    exact = PageMatch(
        match_type="exact_text_duplicate",
        confidence=0.99,
        page_a=left,
        page_b=right,
        signals=[MatchSignal("exact_normalized_text_hash", 1.0)],
        candidate_stage="deterministic_exact",
    )

    matches = apply_embedding_detector([exact], config, pages_a=[left], pages_b=[right])

    assert len(matches) == 1
    assert matches[0].match_type == "exact_text_duplicate"
    assert not any(signal.name == "embedding_similarity" for signal in matches[0].signals)
