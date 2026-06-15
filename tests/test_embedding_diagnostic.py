from __future__ import annotations

import csv
from pathlib import Path

import pytest

from dupe_engine.embedding_diagnostic import (
    GROUP_KN,
    GROUP_PARTIAL,
    GROUP_TP,
    GROUP_UNLABELED,
    build_report,
    classify_group,
    enrich_row,
    is_pure_embedding,
    numeric_stats,
    parse_passes,
    parse_signals,
    render_markdown,
    write_outputs,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_row(
    *,
    candidate_category: str = "semantic_recall",
    match_type: str = "embedding_similarity_candidate",
    candidate_stage: str = "vector_recall",
    truth_label: str = "duplicate",
    confidence: float = 0.88,
    a_best_word_count: int = 120,
    b_best_word_count: int = 115,
    a_text_source: str = "native",
    b_text_source: str = "native",
    a_document: str = "doc_a.pdf",
    b_document: str = "doc_b.pdf",
    signals: str = "embedding_similarity=0.8800",
    deterministic_passes: str = "",
    a_tesseract_attempted: str = "False",
    b_tesseract_attempted: str = "False",
    a_tesseract_usable: str = "False",
    b_tesseract_usable: str = "False",
    a_openai_ocr_selected: str = "False",
    b_openai_ocr_selected: str = "False",
    a_low_information: str = "False",
    b_low_information: str = "False",
    review_bucket: str = "needs_review",
    a_ocr_route: str = "native_only",
    b_ocr_route: str = "native_only",
) -> dict[str, str]:
    return {
        "candidate_category": candidate_category,
        "match_type": match_type,
        "candidate_stage": candidate_stage,
        "truth_label": truth_label,
        "confidence": str(confidence),
        "a_best_word_count": str(a_best_word_count),
        "b_best_word_count": str(b_best_word_count),
        "a_text_source": a_text_source,
        "b_text_source": b_text_source,
        "a_document": a_document,
        "b_document": b_document,
        "signals": signals,
        "deterministic_passes": deterministic_passes,
        "a_tesseract_attempted": a_tesseract_attempted,
        "b_tesseract_attempted": b_tesseract_attempted,
        "a_tesseract_usable": a_tesseract_usable,
        "b_tesseract_usable": b_tesseract_usable,
        "a_openai_ocr_selected": a_openai_ocr_selected,
        "b_openai_ocr_selected": b_openai_ocr_selected,
        "a_low_information": a_low_information,
        "b_low_information": b_low_information,
        "review_bucket": review_bucket,
        "a_ocr_route": a_ocr_route,
        "b_ocr_route": b_ocr_route,
        "rank": "1",
        "truth_kind": "unspecified",
        "truth_notes": "",
        "engine_candidate_label": "needs_review",
        "adjudicator_suggested_label": "",
        "human_final_label": "",
        "visibility": "main_review_list",
        "visibility_reason": "",
        "review_priority": "medium",
        "review_rationale": "",
        "recommendation": "review",
        "a_page": "1",
        "b_page": "1",
        "a_openai_ocr_skip_reason": "",
        "b_openai_ocr_skip_reason": "",
        "embedding_escalation": "True",
        "llm_detector_escalation": "False",
        "adjudicator_escalation": "False",
    }


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# parse_signals / parse_passes
# ---------------------------------------------------------------------------

def test_parse_signals_basic() -> None:
    result = parse_signals("embedding_similarity=0.8765; key_token_overlap=0.5000")
    assert result["embedding_similarity"] == pytest.approx(0.8765)
    assert result["key_token_overlap"] == pytest.approx(0.5000)


def test_parse_signals_empty() -> None:
    assert parse_signals("") == {}
    assert parse_signals("   ") == {}


def test_parse_passes_basic() -> None:
    result = parse_passes("text_exact:no; perceptual_hash:yes; key_token:no")
    assert result["text_exact"] is False
    assert result["perceptual_hash"] is True
    assert result["key_token"] is False


def test_parse_passes_empty() -> None:
    assert parse_passes("") == {}


# ---------------------------------------------------------------------------
# classify_group
# ---------------------------------------------------------------------------

def test_classify_group_tp() -> None:
    assert classify_group({"truth_label": "duplicate"}) == GROUP_TP


def test_classify_group_kn() -> None:
    assert classify_group({"truth_label": "not_duplicate"}) == GROUP_KN


def test_classify_group_partial() -> None:
    assert classify_group({"truth_label": "partial_overlap"}) == GROUP_PARTIAL


def test_classify_group_unlabeled() -> None:
    assert classify_group({"truth_label": "unlabeled"}) == GROUP_UNLABELED
    assert classify_group({}) == GROUP_UNLABELED


# ---------------------------------------------------------------------------
# is_pure_embedding
# ---------------------------------------------------------------------------

def test_is_pure_embedding_true() -> None:
    assert is_pure_embedding({"candidate_category": "semantic_recall"}) is True


def test_is_pure_embedding_false() -> None:
    assert is_pure_embedding({"candidate_category": "standard"}) is False
    assert is_pure_embedding({"candidate_category": ""}) is False


# ---------------------------------------------------------------------------
# enrich_row
# ---------------------------------------------------------------------------

def test_enrich_row_pure_embedding_tp() -> None:
    row = _make_row(
        truth_label="duplicate",
        confidence=0.91,
        signals="embedding_similarity=0.9100",
        deterministic_passes="",
    )
    enriched = enrich_row(row)
    assert enriched["diag_group"] == GROUP_TP
    assert enriched["diag_emb_score"] == pytest.approx(0.91)
    assert enriched["diag_has_key_token_signal"] is False
    assert enriched["diag_has_rare_token_signal"] is False
    assert enriched["diag_has_det_pass_matched"] is False
    assert enriched["diag_has_supporting_evidence"] is False
    assert enriched["diag_has_non_embedding_signal"] is False


def test_enrich_row_with_key_token_signal() -> None:
    row = _make_row(
        signals="embedding_similarity=0.8200; key_token_overlap=0.6000",
        deterministic_passes="",
    )
    enriched = enrich_row(row)
    assert enriched["diag_has_key_token_signal"] is True
    assert enriched["diag_key_token_score"] == pytest.approx(0.6)
    assert enriched["diag_has_non_embedding_signal"] is True
    assert enriched["diag_has_supporting_evidence"] is True


def test_enrich_row_with_matched_pass() -> None:
    row = _make_row(
        signals="embedding_similarity=0.8200",
        deterministic_passes="text_exact:no; perceptual_hash:yes",
    )
    enriched = enrich_row(row)
    assert enriched["diag_has_det_pass_matched"] is True
    assert enriched["diag_has_perceptual_support"] is True
    assert enriched["diag_has_supporting_evidence"] is True
    assert "perceptual_hash" in enriched["diag_matched_passes"]


def test_enrich_row_same_document() -> None:
    row = _make_row(a_document="doc_a.pdf", b_document="doc_a.pdf")
    enriched = enrich_row(row)
    assert enriched["diag_same_document"] is True


def test_enrich_row_cross_document() -> None:
    row = _make_row(a_document="doc_a.pdf", b_document="doc_b.pdf")
    enriched = enrich_row(row)
    assert enriched["diag_same_document"] is False


def test_enrich_row_kn() -> None:
    row = _make_row(truth_label="not_duplicate", confidence=0.76)
    enriched = enrich_row(row)
    assert enriched["diag_group"] == GROUP_KN


# ---------------------------------------------------------------------------
# numeric_stats
# ---------------------------------------------------------------------------

def test_numeric_stats_basic() -> None:
    stats = numeric_stats([1.0, 2.0, 3.0, 4.0, 5.0])
    assert stats["n"] == 5
    assert stats["min"] == pytest.approx(1.0)
    assert stats["max"] == pytest.approx(5.0)
    assert stats["mean"] == pytest.approx(3.0)
    assert stats["median"] == pytest.approx(3.0)


def test_numeric_stats_empty() -> None:
    stats = numeric_stats([])
    assert stats["n"] == 0
    assert stats["min"] is None


def test_numeric_stats_ignores_none() -> None:
    stats = numeric_stats([1.0, None, 3.0])
    assert stats["n"] == 2
    assert stats["mean"] == pytest.approx(2.0)


# ---------------------------------------------------------------------------
# build_report
# ---------------------------------------------------------------------------

def _build_test_csv(tmp_path: Path) -> Path:
    rows = [
        # 3 pure TP rows
        _make_row(truth_label="duplicate", confidence=0.91, signals="embedding_similarity=0.9100"),
        _make_row(truth_label="duplicate", confidence=0.88, signals="embedding_similarity=0.8800",
                  a_best_word_count=200, b_best_word_count=195),
        _make_row(truth_label="duplicate", confidence=0.85, signals="embedding_similarity=0.8500; key_token_overlap=0.6000",
                  deterministic_passes="key_token:yes"),
        # 2 pure KN rows
        _make_row(truth_label="not_duplicate", confidence=0.80, signals="embedding_similarity=0.8000",
                  a_best_word_count=15, b_best_word_count=10),
        _make_row(truth_label="not_duplicate", confidence=0.77, signals="embedding_similarity=0.7700",
                  a_best_word_count=8, b_best_word_count=5),
        # 1 non-pure-embedding row (should be excluded)
        {**_make_row(truth_label="duplicate", candidate_category="standard"), "candidate_category": "standard"},
        # 1 partial overlap
        _make_row(truth_label="partial_overlap", confidence=0.82, candidate_category="semantic_recall"),
    ]
    p = tmp_path / "candidate_summary.csv"
    _write_csv(p, rows)
    return p


def test_build_report_cohort_counts(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)

    assert report["total_rows"] == 7
    assert report["pure_embedding_count"] == 6  # 3 tp + 2 kn + 1 partial
    assert report["other_candidate_count"] == 1
    assert report["cohort"]["tp"] == 3
    assert report["cohort"]["kn"] == 2
    assert report["cohort"]["partial"] == 1
    assert report["cohort"]["unlabeled"] == 0


def test_build_report_feature_comparison(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)

    fc = report["feature_comparison"]
    # TP mean confidence should be higher than KN mean confidence
    tp_mean_conf = fc["embedding_confidence"]["tp"]["mean"]
    kn_mean_conf = fc["embedding_confidence"]["kn"]["mean"]
    assert tp_mean_conf is not None and kn_mean_conf is not None
    assert tp_mean_conf > kn_mean_conf

    # TP mean word count should be higher (from test data)
    tp_min_wc = fc["min_word_count"]["tp"]["mean"]
    kn_min_wc = fc["min_word_count"]["kn"]["mean"]
    assert tp_min_wc is not None and kn_min_wc is not None
    assert tp_min_wc > kn_min_wc


def test_build_report_signal_analysis(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)

    # embedding_similarity should be in signal_analysis
    sa = report["signal_analysis"]
    assert "embedding_similarity" in sa

    # key_token_overlap appears in one TP row so TP presence_rate > 0
    assert "key_token_overlap" in sa
    tp_pres = sa["key_token_overlap"]["tp"]["presence_rate"]
    kn_pres = sa["key_token_overlap"]["kn"]["presence_rate"]
    assert tp_pres > 0
    assert kn_pres == 0.0 or kn_pres is None or kn_pres == pytest.approx(0.0)


def test_build_report_supporting_evidence(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)

    fc = report["feature_comparison"]
    # 1 out of 3 TP rows has supporting evidence (key_token_overlap signal + pass)
    tp_support = fc["has_supporting_evidence"]["tp"]
    assert tp_support["count_true"] == 1
    # 0 out of 2 KN rows have supporting evidence
    kn_support = fc["has_supporting_evidence"]["kn"]
    assert kn_support["count_true"] == 0


def test_build_report_separating_features_present(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)

    ranked = report["separating_features_ranked"]
    assert len(ranked) > 0
    # All entries have a separation_score
    for item in ranked:
        assert item["separation_score"] is not None
    # Ranked in descending order
    scores = [item["separation_score"] for item in ranked]
    assert scores == sorted(scores, reverse=True)


def test_build_report_rows_tagged(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)

    rows = report["pure_embedding_rows"]
    assert len(rows) == 6
    groups = {r["diag_group"] for r in rows}
    assert GROUP_TP in groups
    assert GROUP_KN in groups


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

def test_render_markdown_contains_key_sections(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)
    md = render_markdown(report)

    assert "## Cohort Overview" in md
    assert "## Feature Comparison" in md
    assert "## Separating Features" in md
    assert "semantic_recall" in md
    # Note about missing word count granularity
    assert "Native / Tesseract / OpenAI" in md


# ---------------------------------------------------------------------------
# write_outputs
# ---------------------------------------------------------------------------

def test_write_outputs_creates_files(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)
    out_dir = tmp_path / "diag_out"
    write_outputs(report, out_dir)

    assert (out_dir / "embedding_diagnostic.md").exists()
    assert (out_dir / "embedding_diagnostic.json").exists()
    assert (out_dir / "embedding_diagnostic_rows.csv").exists()


def test_write_outputs_rows_csv_has_diag_columns(tmp_path: Path) -> None:
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)
    out_dir = tmp_path / "diag_out"
    write_outputs(report, out_dir)

    import csv as _csv
    with (out_dir / "embedding_diagnostic_rows.csv").open("r", encoding="utf-8", newline="") as f:
        reader = _csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 6
    for row in rows:
        assert "diag_group" in row
        assert "diag_emb_score" in row
        assert "diag_has_supporting_evidence" in row
    groups = {r["diag_group"] for r in rows}
    assert "tp" in groups
    assert "kn" in groups


def test_write_outputs_json_no_rows_key(tmp_path: Path) -> None:
    """JSON summary should not include the large per-row list."""
    import json
    csv_path = _build_test_csv(tmp_path)
    report = build_report(csv_path)
    out_dir = tmp_path / "diag_out"
    write_outputs(report, out_dir)

    data = json.loads((out_dir / "embedding_diagnostic.json").read_text())
    assert "pure_embedding_rows" not in data
    assert "cohort" in data
    assert "feature_comparison" in data
