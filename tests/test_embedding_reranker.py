from __future__ import annotations

import pytest

from dupe_engine.calibration_harness import CalibrationRunSpec, build_eval_command
from dupe_engine.config import EngineConfig
from dupe_engine.embedding_reranker import (
    RerankerParams,
    _DEMOTE_CONFIDENCE,
    apply_embedding_reranker,
    compute_precision_score,
    is_pure_embedding_match,
    params_from_config,
    score_components,
    summarize_reranker,
)
from dupe_engine.models import MatchSignal, PageMatch, PageRecord
from dupe_engine.reporting import build_all_pairs_report


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def make_page(
    *,
    document_name: str = "doc.pdf",
    page_number: int = 1,
    openai_ocr_selected: bool = False,
    tesseract_usable: bool = False,
    best_word_count: int = 40,
    group: str = "grp",
    document_id: str = "doc",
    image_path: str = "page.png",
) -> PageRecord:
    p = PageRecord(
        group=group,
        document_id=document_id,
        document_name=document_name,
        page_number=page_number,
        image_path=image_path,
        best_word_count=best_word_count,
    )
    p.openai_ocr_selected = openai_ocr_selected
    p.tesseract_usable = tesseract_usable
    return p


def make_embedding_match(
    *,
    confidence: float = 0.90,
    same_doc: bool = False,
    a_ocr: bool = False,
    b_ocr: bool = False,
    a_tess: bool = False,
    b_tess: bool = False,
    match_type: str = "embedding_similarity_candidate",
) -> PageMatch:
    doc_a = "shared.pdf" if same_doc else "doc_a.pdf"
    doc_b = "shared.pdf" if same_doc else "doc_b.pdf"
    page_a = make_page(document_name=doc_a, page_number=1, openai_ocr_selected=a_ocr, tesseract_usable=a_tess)
    page_b = make_page(document_name=doc_b, page_number=2, openai_ocr_selected=b_ocr, tesseract_usable=b_tess)
    return PageMatch(
        match_type=match_type,
        confidence=confidence,
        page_a=page_a,
        page_b=page_b,
        signals=[MatchSignal(name="embedding_similarity", score=confidence)],
        candidate_stage="vector_recall",
        review_bucket="needs_review",
        review_rationale="",
        engine_candidate_label="needs_review",
        visibility="main_review_list",
        visibility_reason="",
        candidate_category="standard",
    )


def enabled_config(**kwargs) -> EngineConfig:
    defaults = dict(
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.88,
        embedding_reranker_ocr_penalty=0.05,
        embedding_reranker_same_doc_bonus=0.03,
        embedding_reranker_tesseract_bonus=0.02,
        embedding_reranker_action="demote",
    )
    defaults.update(kwargs)
    return EngineConfig(**defaults)


# ---------------------------------------------------------------------------
# score_components
# ---------------------------------------------------------------------------

def test_score_components_no_adjustments() -> None:
    params = RerankerParams(min_confidence=0.88, ocr_penalty=0.05, same_doc_bonus=0.03, tesseract_bonus=0.02, action="demote")
    score, components = score_components(
        confidence=0.90, a_ocr=False, b_ocr=False, a_tesseract=False, b_tesseract=False, same_doc=False, params=params
    )
    assert score == pytest.approx(0.90)
    assert components["ocr_penalty_total"] == pytest.approx(0.0)
    assert components["tesseract_bonus_total"] == pytest.approx(0.0)
    assert components["same_document_bonus"] == pytest.approx(0.0)


def test_score_components_single_ocr_penalty() -> None:
    params = RerankerParams(min_confidence=0.88, ocr_penalty=0.05, same_doc_bonus=0.03, tesseract_bonus=0.02, action="demote")
    score, components = score_components(
        confidence=0.87, a_ocr=True, b_ocr=False, a_tesseract=False, b_tesseract=False, same_doc=False, params=params
    )
    assert score == pytest.approx(0.82)
    assert components["ocr_penalty_total"] == pytest.approx(0.05)


def test_score_components_double_ocr_penalty() -> None:
    params = RerankerParams(min_confidence=0.88, ocr_penalty=0.05, same_doc_bonus=0.03, tesseract_bonus=0.02, action="demote")
    score, _ = score_components(
        confidence=0.87, a_ocr=True, b_ocr=True, a_tesseract=False, b_tesseract=False, same_doc=False, params=params
    )
    assert score == pytest.approx(0.77)


def test_score_components_same_doc_bonus() -> None:
    params = RerankerParams(min_confidence=0.88, ocr_penalty=0.05, same_doc_bonus=0.03, tesseract_bonus=0.02, action="demote")
    score, components = score_components(
        confidence=0.86, a_ocr=False, b_ocr=False, a_tesseract=False, b_tesseract=False, same_doc=True, params=params
    )
    assert score == pytest.approx(0.89)
    assert components["same_document_bonus"] == pytest.approx(0.03)


def test_score_components_clamped_to_one() -> None:
    params = RerankerParams(min_confidence=0.88, ocr_penalty=0.05, same_doc_bonus=0.03, tesseract_bonus=0.02, action="demote")
    score, _ = score_components(
        confidence=0.99, a_ocr=False, b_ocr=False, a_tesseract=True, b_tesseract=True, same_doc=True, params=params
    )
    assert score == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# is_pure_embedding_match
# ---------------------------------------------------------------------------

def test_is_pure_embedding_true() -> None:
    m = make_embedding_match()
    assert is_pure_embedding_match(m) is True


def test_is_pure_embedding_false_for_other_types() -> None:
    m = make_embedding_match(match_type="exact_text_duplicate")
    assert is_pure_embedding_match(m) is False


# ---------------------------------------------------------------------------
# params_from_config
# ---------------------------------------------------------------------------

def test_params_from_config_defaults() -> None:
    # Phase 4 approved defaults: min_confidence=0.80, ocr_penalty=0.01
    config = EngineConfig()
    params = params_from_config(config)
    assert params.min_confidence == pytest.approx(0.80)
    assert params.ocr_penalty == pytest.approx(0.01)
    assert params.same_doc_bonus == pytest.approx(0.03)
    assert params.tesseract_bonus == pytest.approx(0.02)
    assert params.action == "demote"


def test_params_from_config_invalid_action_falls_back_to_demote() -> None:
    config = EngineConfig(embedding_reranker_action="invalid_action")
    params = params_from_config(config)
    assert params.action == "demote"


# ---------------------------------------------------------------------------
# Case 1: high confidence same-document keeps
# ---------------------------------------------------------------------------

def test_high_confidence_same_doc_is_kept() -> None:
    config = enabled_config()
    match = make_embedding_match(confidence=0.92, same_doc=True)
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.92)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert len(events) == 1
    assert events[0]["decision"] == "keep"


# ---------------------------------------------------------------------------
# Case 2: high confidence cross-document keeps
# ---------------------------------------------------------------------------

def test_high_confidence_cross_doc_is_kept() -> None:
    config = enabled_config()
    match = make_embedding_match(confidence=0.91, same_doc=False, a_ocr=False)
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.91)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert events[0]["decision"] == "keep"


# ---------------------------------------------------------------------------
# Case 3: low confidence OCR-dependent demotes
# ---------------------------------------------------------------------------

def test_low_confidence_ocr_dependent_is_demoted() -> None:
    config = enabled_config()
    match = make_embedding_match(confidence=0.85, same_doc=False, a_ocr=True)
    # score = 0.85 - 0.05 = 0.80 < 0.88 → demote
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(_DEMOTE_CONFIDENCE)
    assert result[0].review_rationale.startswith("embedding_reranker_demoted")
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert events[0]["decision"] == "demote"


# ---------------------------------------------------------------------------
# Case 4: double OCR penalty demotes
# ---------------------------------------------------------------------------

def test_double_ocr_both_pages_is_demoted() -> None:
    config = enabled_config()
    match = make_embedding_match(confidence=0.87, same_doc=False, a_ocr=True, b_ocr=True)
    # score = 0.87 - 0.05 - 0.05 = 0.77 < 0.88 → demote
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(_DEMOTE_CONFIDENCE)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert events[0]["decision"] == "demote"
    assert events[0]["components"]["ocr_penalty_total"] == pytest.approx(0.10)


# ---------------------------------------------------------------------------
# Case 5: same-document bonus rescues borderline
# ---------------------------------------------------------------------------

def test_same_doc_bonus_rescues_borderline() -> None:
    # conf=0.86, same_doc=True → score = 0.86 + 0.03 = 0.89 >= 0.88 → keep
    config = enabled_config(
        embedding_reranker_min_confidence=0.88,
        embedding_reranker_same_doc_bonus=0.03,
    )
    match = make_embedding_match(confidence=0.86, same_doc=True, a_ocr=False)
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.86)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert events[0]["decision"] == "keep"
    assert events[0]["components"]["precision_score"] == pytest.approx(0.89)


# ---------------------------------------------------------------------------
# Case 6: non-pure candidates are untouched
# ---------------------------------------------------------------------------

def test_non_pure_candidate_is_untouched() -> None:
    config = enabled_config()
    match = make_embedding_match(match_type="multi_signal_candidate", confidence=0.75)
    original_conf = match.confidence
    original_rationale = match.review_rationale
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(original_conf)
    assert result[0].review_rationale == original_rationale
    reranker_events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert len(reranker_events) == 0


# ---------------------------------------------------------------------------
# Case 7: disabled config is exact pass-through
# ---------------------------------------------------------------------------

def test_disabled_config_is_pass_through() -> None:
    config = EngineConfig(embedding_reranker_enabled=False)
    matches = [
        make_embedding_match(confidence=0.75),  # would be demoted if enabled
        make_embedding_match(confidence=0.92),
    ]
    result = apply_embedding_reranker(matches, config)
    assert result is matches  # same list object
    assert result[0].confidence == pytest.approx(0.75)
    assert result[1].confidence == pytest.approx(0.92)
    for m in result:
        reranker_events = [e for e in m.ai_route_events if e.get("route") == "embedding_reranker"]
        assert len(reranker_events) == 0


# ---------------------------------------------------------------------------
# Case 8: drop action zeroes confidence (kept for audit trail)
# ---------------------------------------------------------------------------

def test_drop_action_zeroes_confidence() -> None:
    # drop sets confidence=0.0 and routes to calibration_only rather than
    # removing the row, so summarize_reranker can count the event in the audit trail.
    config = enabled_config(embedding_reranker_action="drop")
    low = make_embedding_match(confidence=0.80, a_ocr=True)   # score=0.75 → drop
    high = make_embedding_match(confidence=0.92)               # kept
    result = apply_embedding_reranker([low, high], config)
    assert len(result) == 2
    dropped = next(m for m in result if m.confidence == pytest.approx(0.0))
    kept = next(m for m in result if m.confidence != pytest.approx(0.0))
    assert dropped is not None
    assert kept.confidence == pytest.approx(0.92)


def test_drop_action_event_attached_to_dropped_match() -> None:
    config = enabled_config(embedding_reranker_action="drop")
    match = make_embedding_match(confidence=0.80, a_ocr=True)
    apply_embedding_reranker([match], config)
    reranker_events = [e for e in match.ai_route_events if e.get("route") == "embedding_reranker"]
    assert len(reranker_events) == 1
    assert reranker_events[0]["decision"] == "drop"


# ---------------------------------------------------------------------------
# Case 9: demoted match has complete trace event
# ---------------------------------------------------------------------------

def test_demoted_match_has_trace_event() -> None:
    config = enabled_config()
    match = make_embedding_match(confidence=0.85, a_ocr=True)
    result = apply_embedding_reranker([match], config)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert len(events) == 1
    event = events[0]
    assert event["route"] == "embedding_reranker"
    assert event["decision"] == "demote"
    assert "original_confidence" in event
    assert "precision_score" in event
    assert "components" in event
    comps = event["components"]
    assert "base_confidence" in comps
    assert "precision_score" in comps
    assert "min_confidence" in comps
    assert event["original_confidence"] == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Case 10: demotion survives annotation guard (minimum safe behavior)
# ---------------------------------------------------------------------------

def test_demoted_match_confidence_and_rationale() -> None:
    config = enabled_config()
    match = make_embedding_match(confidence=0.85, a_ocr=True)
    result = apply_embedding_reranker([match], config)
    demoted = result[0]
    # Confidence is at demotion level
    assert demoted.confidence == pytest.approx(_DEMOTE_CONFIDENCE)
    # review_rationale is non-empty and tagged — calibration guard won't overwrite it
    assert demoted.review_rationale.startswith("embedding_reranker_demoted")
    # Visibility reflects lowered confidence (calibration_only or secondary_review,
    # not main_review_list)
    assert demoted.visibility != "main_review_list"


# ---------------------------------------------------------------------------
# summarize_reranker
# ---------------------------------------------------------------------------

def test_summarize_reranker_counts() -> None:
    config = enabled_config()
    matches = [
        make_embedding_match(confidence=0.92),          # keep
        make_embedding_match(confidence=0.85, a_ocr=True),   # demote
        make_embedding_match(confidence=0.90, same_doc=True), # keep
    ]
    result = apply_embedding_reranker(matches, config)
    summary = summarize_reranker(result)
    assert summary["evaluated"] == 3
    assert summary["kept"] == 2
    assert summary["demoted"] == 1
    assert summary["dropped"] == 0
    assert summary["min_precision_score"] is not None
    assert summary["max_precision_score"] is not None


# ---------------------------------------------------------------------------
# Phase 4: integration — reranker disabled leaves matches unchanged
# ---------------------------------------------------------------------------

def test_reranker_disabled_leaves_matches_unchanged() -> None:
    config = EngineConfig(embedding_reranker_enabled=False)
    # even a match that would be demoted under enabled config survives
    match = make_embedding_match(confidence=0.75, a_ocr=True)
    original_conf = match.confidence
    result = apply_embedding_reranker([match], config)
    assert result is [match] or result[0].confidence == pytest.approx(original_conf)
    assert all(
        len([e for e in m.ai_route_events if e.get("route") == "embedding_reranker"]) == 0
        for m in result
    )


# Phase 4: integration — reranker enabled demotes eligible pure embedding candidates

def test_reranker_enabled_demotes_eligible_candidates() -> None:
    config = EngineConfig(
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.80,
        embedding_reranker_ocr_penalty=0.01,
        embedding_reranker_same_doc_bonus=0.03,
        embedding_reranker_tesseract_bonus=0.02,
        embedding_reranker_action="demote",
    )
    # confidence=0.79 + ocr_penalty=0.01 → score=0.78 < 0.80 → demote
    match = make_embedding_match(confidence=0.79, a_ocr=True)
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(_DEMOTE_CONFIDENCE)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert events[0]["decision"] == "demote"


# Phase 4: integration — approved setting keeps high-confidence match

def test_approved_setting_keeps_high_confidence() -> None:
    config = EngineConfig(
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.80,
        embedding_reranker_ocr_penalty=0.01,
        embedding_reranker_same_doc_bonus=0.03,
        embedding_reranker_tesseract_bonus=0.02,
        embedding_reranker_action="demote",
    )
    # confidence=0.85, no OCR dependency → score=0.85 >= 0.80 → keep
    match = make_embedding_match(confidence=0.85)
    result = apply_embedding_reranker([match], config)
    assert len(result) == 1
    assert result[0].confidence == pytest.approx(0.85)
    events = [e for e in result[0].ai_route_events if e.get("route") == "embedding_reranker"]
    assert events[0]["decision"] == "keep"


# Phase 4: integration — non-embedding candidates are untouched

def test_non_embedding_candidates_untouched_by_reranker() -> None:
    config = EngineConfig(
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.80,
        embedding_reranker_ocr_penalty=0.01,
    )
    det = make_embedding_match(match_type="exact_text_duplicate", confidence=0.99)
    multi = make_embedding_match(match_type="multi_signal_candidate", confidence=0.70)
    result = apply_embedding_reranker([det, multi], config)
    assert len(result) == 2
    assert result[0].confidence == pytest.approx(0.99)
    assert result[1].confidence == pytest.approx(0.70)
    for m in result:
        reranker_events = [e for e in m.ai_route_events if e.get("route") == "embedding_reranker"]
        assert len(reranker_events) == 0


# Phase 4: integration — reranker stats appear in report summary

def test_reranker_stats_in_report_summary() -> None:
    config = EngineConfig(
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.80,
        embedding_reranker_ocr_penalty=0.01,
        embedding_reranker_same_doc_bonus=0.03,
        embedding_reranker_tesseract_bonus=0.02,
        embedding_reranker_action="demote",
    )
    matches = [
        make_embedding_match(confidence=0.92),
        make_embedding_match(confidence=0.75, a_ocr=True),  # demoted
    ]
    processed = apply_embedding_reranker(matches, config)
    report = build_all_pairs_report(pages=[], matches=processed, config=config)
    reranker_summary = report["summary"].get("embedding_reranker")
    assert reranker_summary is not None
    assert reranker_summary["evaluated"] == 2
    assert reranker_summary["demoted"] == 1
    assert reranker_summary["kept"] == 1


# Phase 4: integration — calibration harness emits reranker CLI flags

def test_calibration_harness_emits_reranker_flags() -> None:
    from pathlib import Path
    import types

    spec = CalibrationRunSpec(
        run_id="test_run",
        stage="vector",
        profile_name="balanced",
        ocr_cap=75,
        ocr_selection_mode="reason_balanced",
        ocr_reason_quotas="vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20",
        vector_profile="balanced",
        embeddings_enabled=True,
        embedding_top_k=5,
        embedding_min_similarity=0.85,
        embedding_min_margin=0.03,
        embedding_max_candidates_per_page=2,
        embedding_max_candidates_per_job=300,
        embedding_min_text_chars=150,
        queue_profile="balanced",
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.80,
        embedding_reranker_ocr_penalty=0.01,
        embedding_reranker_same_doc_bonus=0.03,
        embedding_reranker_tesseract_bonus=0.02,
        embedding_reranker_action="demote",
    )
    args = types.SimpleNamespace(dpi=150, tesseract_profiles="standard,grayscale,high_contrast")
    cmd = build_eval_command(spec, Path("/data/pdf"), Path("/data/truth.json"), Path("/data/run"), args)
    cmd_str = " ".join(cmd)
    assert "--embedding-reranker" in cmd_str
    assert "--embedding-reranker-min-confidence" in cmd_str
    assert "0.8" in cmd_str  # Python str(0.80) == "0.8"
    assert "--embedding-reranker-ocr-penalty" in cmd_str
    assert "0.01" in cmd_str
    assert "--embedding-reranker-action" in cmd_str
    assert "demote" in cmd_str


# Phase 4: integration — scorecard includes reranker columns

def test_scorecard_spec_has_reranker_fields() -> None:
    spec = CalibrationRunSpec(
        run_id="test_run",
        stage="vector",
        profile_name="balanced",
        ocr_cap=75,
        ocr_selection_mode="reason_balanced",
        ocr_reason_quotas="vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20",
        vector_profile="balanced",
        embeddings_enabled=True,
        embedding_top_k=5,
        embedding_min_similarity=0.85,
        embedding_min_margin=0.03,
        embedding_max_candidates_per_page=2,
        embedding_max_candidates_per_job=300,
        embedding_min_text_chars=150,
        queue_profile="balanced",
        embedding_reranker_enabled=True,
        embedding_reranker_min_confidence=0.80,
        embedding_reranker_ocr_penalty=0.01,
        embedding_reranker_same_doc_bonus=0.03,
        embedding_reranker_tesseract_bonus=0.02,
        embedding_reranker_action="demote",
    )
    assert spec.embedding_reranker_enabled is True
    assert spec.embedding_reranker_min_confidence == pytest.approx(0.80)
    assert spec.embedding_reranker_ocr_penalty == pytest.approx(0.01)
    assert spec.embedding_reranker_same_doc_bonus == pytest.approx(0.03)
    assert spec.embedding_reranker_tesseract_bonus == pytest.approx(0.02)
    assert spec.embedding_reranker_action == "demote"


# Phase 4: integration — harness emits no reranker flags when disabled

def test_calibration_harness_no_reranker_flags_when_disabled() -> None:
    from pathlib import Path
    import types

    spec = CalibrationRunSpec(
        run_id="test_run",
        stage="vector",
        profile_name="balanced",
        ocr_cap=75,
        ocr_selection_mode="reason_balanced",
        ocr_reason_quotas="vision_expected:30,weak_tesseract:30,no_text:20,candidate_based:20",
        vector_profile="balanced",
        embeddings_enabled=True,
        embedding_top_k=5,
        embedding_min_similarity=0.85,
        embedding_min_margin=0.03,
        embedding_max_candidates_per_page=2,
        embedding_max_candidates_per_job=300,
        embedding_min_text_chars=150,
        queue_profile="balanced",
        embedding_reranker_enabled=False,
    )
    args = types.SimpleNamespace(dpi=150, tesseract_profiles="standard,grayscale,high_contrast")
    cmd = build_eval_command(spec, Path("/data/pdf"), Path("/data/truth.json"), Path("/data/run"), args)
    assert "--embedding-reranker" not in cmd
