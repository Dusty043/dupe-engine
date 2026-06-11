from __future__ import annotations

from dupe_engine.capabilities import build_capability_report
from dupe_engine.config import EngineConfig


def test_ocr_and_openai_fallback_are_enabled_and_required_by_default(monkeypatch) -> None:
    monkeypatch.delenv("DUPE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = build_capability_report(EngineConfig())
    assert report.layers["exact_image_hash"].available is True
    assert report.layers["ocr"].enabled is True
    assert report.layers["ocr"].required is True
    assert report.layers["openai_ocr_fallback"].enabled is True
    assert report.layers["openai_ocr_fallback"].required is True
    assert report.layers["openai_ocr_fallback"].status == "unavailable"
    assert report.blocking_errors
    assert report.layers["embeddings"].status == "disabled"
    assert report.layers["llm_candidate_detector"].status == "disabled"
    assert report.layers["adjudicator_agent"].status == "disabled"


def test_embedding_status_reports_missing_openai_key(monkeypatch) -> None:
    monkeypatch.delenv("DUPE_EMBEDDINGS_API_KEY", raising=False)
    monkeypatch.delenv("DUPE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = build_capability_report(EngineConfig(enable_embeddings=True, embeddings_provider="openai"))
    status = report.layers["embeddings"]
    assert status.enabled is True
    assert status.available is False
    assert status.status == "unavailable"
    assert "OPENAI_API_KEY" in (status.reason or "")


def test_required_unavailable_layer_blocks_run(monkeypatch) -> None:
    monkeypatch.delenv("DUPE_EMBEDDINGS_API_KEY", raising=False)
    monkeypatch.delenv("DUPE_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    report = build_capability_report(EngineConfig(enable_embeddings=True, require_embeddings=True))
    assert report.blocking_errors


def test_llm_roles_are_separate() -> None:
    report = build_capability_report(
        EngineConfig(
            enable_llm_candidate_detector=True,
            enable_adjudicator=True,
            llm_candidate_provider="openai",
            adjudicator_provider="openai",
        )
    )
    assert report.layers["llm_candidate_detector"].role == "detector"
    assert report.layers["adjudicator_agent"].role == "adjudicator"


def test_route_specific_openai_key_overrides_unified_key(monkeypatch) -> None:
    from dupe_engine.capabilities import get_openai_ocr_api_key

    monkeypatch.setenv("DUPE_OPENAI_API_KEY", "unified")
    monkeypatch.setenv("MY_OCR_KEY", "specific")
    config = EngineConfig(openai_ocr_api_key_env="MY_OCR_KEY")

    assert get_openai_ocr_api_key(config) == "specific"


def test_unified_openai_key_feeds_embeddings(monkeypatch) -> None:
    monkeypatch.setenv("DUPE_OPENAI_API_KEY", "unified")
    report = build_capability_report(EngineConfig(enable_embeddings=True, embeddings_provider="openai"))

    assert report.layers["embeddings"].status == "available"


def test_unified_openai_key_makes_required_ocr_fallback_available(monkeypatch) -> None:
    monkeypatch.setenv("DUPE_OPENAI_API_KEY", "test-key")
    report = build_capability_report(EngineConfig())
    status = report.layers["openai_ocr_fallback"]
    assert status.enabled is True
    assert status.required is True
    assert status.available is True
    assert status.status == "available"
    assert not report.blocking_errors
