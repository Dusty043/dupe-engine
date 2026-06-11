"""v0.10.9 offline diagnostic: pure embedding candidate TP vs KN comparison.

Reads candidate_summary.csv from a v0.10.8 widened run and compares
pure embedding true positives against pure embedding known-negative hits.

"Pure embedding" is defined as candidate_category=semantic_recall.
review.py sets this when the candidate stage is vector_recall/embedding_recall
and signals are only embedding_similarity or hybrid_vector_score—meaning no
deterministic text or visual layers contributed independently.

Features reported per the v0.10.9 plan:
  - embedding confidence
  - OCR/text source
  - best word counts (native/Tesseract/OpenAI not in candidate_summary.csv)
  - key-token overlap signal presence/score
  - rare-token overlap signal presence/score
  - visual/perceptual hash signal or pass presence
  - sequence signal presence
  - source document families
  - review bucket
  - candidate category
  - deterministic pass support
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "dupe_engine_embedding_diagnostic_v0_10_9"

PURE_EMBEDDING_CATEGORIES: frozenset[str] = frozenset({"semantic_recall"})
PURE_EMBEDDING_MATCH_TYPES: frozenset[str] = frozenset({
    "embedding_similarity_candidate",
    "hybrid_vector_candidate",
})
PURE_EMBEDDING_STAGES: frozenset[str] = frozenset({
    "vector_recall",
    "embedding_recall",
    "hybrid_vector_recall",
})

GROUP_TP = "tp"
GROUP_KN = "kn"
GROUP_PARTIAL = "partial"
GROUP_UNLABELED = "unlabeled"

_SIGNAL_PATTERN = re.compile(r"([A-Za-z0-9_]+)=([\d.]+(?:e[+-]?\d+)?)")
_PASS_PATTERN = re.compile(r"([A-Za-z0-9_]+):(yes|no)", re.IGNORECASE)

# Signal name substrings that indicate supporting (non-embedding) evidence
_SUPPORTING_SIGNAL_KEYWORDS = (
    "key_token",
    "rare_token",
    "perceptual",
    "sequence",
    "text_exact",
    "tfidf",
    "hash",
)


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"candidate_summary.csv not found: {path}")
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _as_float(value: Any, default: float | None = None) -> float | None:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        if isinstance(value, float) and math.isnan(value):
            return default
        return float(value)
    s = str(value).strip()
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _as_int(value: Any, default: int = 0) -> int:
    f = _as_float(value, None)
    return int(f) if f is not None else default


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in {"1", "true", "yes", "y"}:
        return True
    if s in {"0", "false", "no", "n"}:
        return False
    return default


# ---------------------------------------------------------------------------
# Parsing signal / pass fields
# ---------------------------------------------------------------------------

def parse_signals(text: str) -> dict[str, float]:
    """Parse 'signal_name=score; ...' into {name: score}."""
    result: dict[str, float] = {}
    for m in _SIGNAL_PATTERN.finditer(str(text or "")):
        try:
            result[m.group(1)] = float(m.group(2))
        except ValueError:
            pass
    return result


def parse_passes(text: str) -> dict[str, bool]:
    """Parse 'pass_name:yes; ...' into {name: matched}."""
    result: dict[str, bool] = {}
    for m in _PASS_PATTERN.finditer(str(text or "")):
        result[m.group(1)] = m.group(2).lower() == "yes"
    return result


# ---------------------------------------------------------------------------
# Row classification
# ---------------------------------------------------------------------------

def classify_group(row: dict[str, str]) -> str:
    label = str(row.get("truth_label") or "").strip().lower()
    if label in {"duplicate", "true_positive"}:
        return GROUP_TP
    if label in {"not_duplicate", "known_negative"}:
        return GROUP_KN
    if label in {"partial_overlap"}:
        return GROUP_PARTIAL
    return GROUP_UNLABELED


def is_pure_embedding(row: dict[str, str]) -> bool:
    """True when the row is a pure embedding candidate."""
    category = str(row.get("candidate_category") or "").strip().lower()
    return category in PURE_EMBEDDING_CATEGORIES


# ---------------------------------------------------------------------------
# Row enrichment
# ---------------------------------------------------------------------------

def enrich_row(row: dict[str, str]) -> dict[str, Any]:
    """Return a copy of row with derived diagnostic columns added."""
    signals = parse_signals(row.get("signals") or "")
    passes = parse_passes(row.get("deterministic_passes") or "")

    emb_score = signals.get("embedding_similarity") or signals.get("hybrid_vector_score") or _as_float(row.get("confidence"))

    key_token_score = next((v for k, v in signals.items() if "key_token" in k), None)
    rare_token_score = next((v for k, v in signals.items() if "rare_token" in k), None)
    perceptual_score = next((v for k, v in signals.items() if "perceptual" in k or ("hash" in k and "text" not in k)), None)
    sequence_score = next((v for k, v in signals.items() if "sequence" in k), None)

    has_key_token_signal = key_token_score is not None
    has_rare_token_signal = rare_token_score is not None
    has_perceptual_signal = perceptual_score is not None
    has_sequence_signal = sequence_score is not None

    # Any non-embedding signal in the signals field
    non_embedding_signals = {k: v for k, v in signals.items() if k not in {"embedding_similarity", "hybrid_vector_score"}}
    has_non_embedding_signal = bool(non_embedding_signals)

    # Any pass that fired (matched=True)
    matched_passes = {k for k, v in passes.items() if v}
    has_det_pass_matched = bool(matched_passes)

    # Perceptual hash pass
    has_perceptual_pass = any("perceptual" in k or ("hash" in k and "text" not in k) for k in matched_passes)
    has_perceptual_support = has_perceptual_signal or has_perceptual_pass

    # Combined: has any supporting evidence
    has_supporting_evidence = has_non_embedding_signal or has_det_pass_matched

    a_wc = _as_int(row.get("a_best_word_count"))
    b_wc = _as_int(row.get("b_best_word_count"))
    min_word_count = min(a_wc, b_wc)
    combined_word_count = a_wc + b_wc

    # Document family: strip trailing page-like suffixes and extensions
    a_doc = str(row.get("a_document") or "")
    b_doc = str(row.get("b_document") or "")
    same_document = a_doc == b_doc and bool(a_doc)

    enriched: dict[str, Any] = dict(row)
    enriched.update({
        "diag_group": classify_group(row),
        "diag_emb_score": emb_score,
        "diag_signals": signals,
        "diag_passes": passes,
        "diag_key_token_score": key_token_score,
        "diag_rare_token_score": rare_token_score,
        "diag_perceptual_score": perceptual_score,
        "diag_sequence_score": sequence_score,
        "diag_has_key_token_signal": has_key_token_signal,
        "diag_has_rare_token_signal": has_rare_token_signal,
        "diag_has_perceptual_signal": has_perceptual_signal,
        "diag_has_sequence_signal": has_sequence_signal,
        "diag_has_non_embedding_signal": has_non_embedding_signal,
        "diag_has_det_pass_matched": has_det_pass_matched,
        "diag_has_perceptual_support": has_perceptual_support,
        "diag_has_supporting_evidence": has_supporting_evidence,
        "diag_matched_passes": sorted(matched_passes),
        "diag_non_embedding_signal_names": sorted(non_embedding_signals.keys()),
        "diag_a_best_word_count": a_wc,
        "diag_b_best_word_count": b_wc,
        "diag_min_word_count": min_word_count,
        "diag_combined_word_count": combined_word_count,
        "diag_same_document": same_document,
        "diag_a_document": a_doc,
        "diag_b_document": b_doc,
    })
    return enriched


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list[float], p: float) -> float | None:
    if not sorted_values:
        return None
    n = len(sorted_values)
    idx = p / 100.0 * (n - 1)
    lo = int(idx)
    hi = lo + 1
    frac = idx - lo
    if hi >= n:
        return sorted_values[-1]
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def numeric_stats(values: list[float | None]) -> dict[str, Any]:
    clean = sorted(v for v in values if v is not None)
    n = len(clean)
    if n == 0:
        return {"n": 0, "min": None, "p25": None, "median": None, "mean": None, "p75": None, "max": None, "std": None}
    mean = sum(clean) / n
    variance = sum((x - mean) ** 2 for x in clean) / n if n > 1 else 0.0
    return {
        "n": n,
        "min": round(clean[0], 4),
        "p25": round(_percentile(clean, 25) or 0, 4),
        "median": round(_percentile(clean, 50) or 0, 4),
        "mean": round(mean, 4),
        "p75": round(_percentile(clean, 75) or 0, 4),
        "max": round(clean[-1], 4),
        "std": round(math.sqrt(variance), 4),
    }


def bool_rate(values: list[bool]) -> dict[str, Any]:
    n = len(values)
    count = sum(1 for v in values if v)
    rate = round(count / n, 4) if n > 0 else None
    return {"n": n, "count_true": count, "rate": rate}


def value_counts(values: list[str]) -> dict[str, int]:
    return dict(Counter(values).most_common())


def _separation_score(tp_values: list[float | None], kn_values: list[float | None]) -> float | None:
    """abs(tp_mean - kn_mean) / pooled_std, or None if insufficient data."""
    tp_clean = [v for v in tp_values if v is not None]
    kn_clean = [v for v in kn_values if v is not None]
    if len(tp_clean) < 2 or len(kn_clean) < 2:
        return None
    tp_mean = sum(tp_clean) / len(tp_clean)
    kn_mean = sum(kn_clean) / len(kn_clean)
    tp_var = sum((x - tp_mean) ** 2 for x in tp_clean) / len(tp_clean)
    kn_var = sum((x - kn_mean) ** 2 for x in kn_clean) / len(kn_clean)
    pooled_std = math.sqrt((tp_var + kn_var) / 2.0)
    if pooled_std < 1e-9:
        return None
    return round(abs(tp_mean - kn_mean) / pooled_std, 4)


def _bool_separation(tp_rows: list[dict], kn_rows: list[dict], key: str) -> float | None:
    if not tp_rows or not kn_rows:
        return None
    tp_rate = sum(1 for r in tp_rows if r.get(key)) / len(tp_rows)
    kn_rate = sum(1 for r in kn_rows if r.get(key)) / len(kn_rows)
    return round(abs(tp_rate - kn_rate), 4)


# ---------------------------------------------------------------------------
# Core report builder
# ---------------------------------------------------------------------------

def _group_rows(rows: list[dict[str, Any]]) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    tp, kn, partial, unlabeled = [], [], [], []
    for row in rows:
        g = row["diag_group"]
        if g == GROUP_TP:
            tp.append(row)
        elif g == GROUP_KN:
            kn.append(row)
        elif g == GROUP_PARTIAL:
            partial.append(row)
        else:
            unlabeled.append(row)
    return tp, kn, partial, unlabeled


def _collect_all_signal_names(rows: list[dict]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        names.update(row.get("diag_signals", {}).keys())
    return sorted(names)


def _collect_all_pass_names(rows: list[dict]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        names.update(row.get("diag_passes", {}).keys())
    return sorted(names)


def _signal_group_stats(rows: list[dict], signal_name: str) -> dict[str, Any]:
    scores: list[float | None] = [row["diag_signals"].get(signal_name) for row in rows]
    present = [s for s in scores if s is not None]
    return {
        "presence_rate": round(len(present) / len(rows), 4) if rows else None,
        "presence_count": len(present),
        "score_stats": numeric_stats(present),
    }


def _pass_group_stats(rows: list[dict], pass_name: str) -> dict[str, Any]:
    matched = [row["diag_passes"].get(pass_name, False) for row in rows]
    n_match = sum(1 for v in matched if v)
    return {
        "matched_rate": round(n_match / len(rows), 4) if rows else None,
        "matched_count": n_match,
    }


def build_report(csv_path: Path) -> dict[str, Any]:
    csv_path = csv_path.resolve()
    all_rows = _read_csv(csv_path)
    total = len(all_rows)

    # Filter to pure embedding candidates
    pure_rows_raw = [r for r in all_rows if is_pure_embedding(r)]
    other_rows_raw = [r for r in all_rows if not is_pure_embedding(r)]

    # Enrich
    pure_rows = [enrich_row(r) for r in pure_rows_raw]
    tp_rows, kn_rows, partial_rows, unlabeled_rows = _group_rows(pure_rows)

    # Coverage
    match_type_counts = value_counts([str(r.get("match_type") or "") for r in pure_rows_raw])
    stage_counts = value_counts([str(r.get("candidate_stage") or "") for r in pure_rows_raw])

    # All signal/pass names in the pure embedding cohort
    all_signal_names = _collect_all_signal_names(pure_rows)
    all_pass_names = _collect_all_pass_names(pure_rows)

    # Feature stats by group
    def _num_field(rows: list[dict], field: str) -> list[float | None]:
        return [_as_float(r.get(field)) for r in rows]

    def _bool_field(rows: list[dict], field: str) -> list[bool]:
        return [bool(r.get(field)) for r in rows]

    def _str_field(rows: list[dict], field: str) -> list[str]:
        return [str(r.get(field) or "") for r in rows]

    feature_comparison: dict[str, Any] = {}

    # Confidence / embedding score
    for name, field in [
        ("embedding_confidence", "confidence"),
        ("a_best_word_count", "diag_a_best_word_count"),
        ("b_best_word_count", "diag_b_best_word_count"),
        ("min_word_count", "diag_min_word_count"),
        ("combined_word_count", "diag_combined_word_count"),
    ]:
        feature_comparison[name] = {
            "tp": numeric_stats(_num_field(tp_rows, field)),
            "kn": numeric_stats(_num_field(kn_rows, field)),
            "all_pure": numeric_stats(_num_field(pure_rows, field)),
            "separation_score": _separation_score(_num_field(tp_rows, field), _num_field(kn_rows, field)),
        }

    # Boolean supporting-evidence features
    bool_features = [
        ("has_key_token_signal", "diag_has_key_token_signal"),
        ("has_rare_token_signal", "diag_has_rare_token_signal"),
        ("has_perceptual_support", "diag_has_perceptual_support"),
        ("has_sequence_signal", "diag_has_sequence_signal"),
        ("has_non_embedding_signal", "diag_has_non_embedding_signal"),
        ("has_det_pass_matched", "diag_has_det_pass_matched"),
        ("has_supporting_evidence", "diag_has_supporting_evidence"),
        ("same_document", "diag_same_document"),
        ("a_tesseract_attempted", "a_tesseract_attempted"),
        ("b_tesseract_attempted", "b_tesseract_attempted"),
        ("a_tesseract_usable", "a_tesseract_usable"),
        ("b_tesseract_usable", "b_tesseract_usable"),
        ("a_openai_ocr_selected", "a_openai_ocr_selected"),
        ("b_openai_ocr_selected", "b_openai_ocr_selected"),
        ("a_low_information", "a_low_information"),
        ("b_low_information", "b_low_information"),
    ]
    for name, field in bool_features:
        tp_vals = [_as_bool(r.get(field)) for r in tp_rows]
        kn_vals = [_as_bool(r.get(field)) for r in kn_rows]
        feature_comparison[name] = {
            "tp": bool_rate(tp_vals),
            "kn": bool_rate(kn_vals),
            "separation_score": _bool_separation(tp_rows, kn_rows, field),
        }

    # Categorical features
    for name, field in [
        ("review_bucket", "review_bucket"),
        ("a_text_source", "a_text_source"),
        ("b_text_source", "b_text_source"),
        ("a_ocr_route", "a_ocr_route"),
        ("b_ocr_route", "b_ocr_route"),
        ("candidate_stage", "candidate_stage"),
        ("match_type", "match_type"),
    ]:
        feature_comparison[name] = {
            "tp": value_counts(_str_field(tp_rows, field)),
            "kn": value_counts(_str_field(kn_rows, field)),
        }

    # Signal-level stats for all signal names found
    signal_analysis: dict[str, Any] = {}
    for sig_name in all_signal_names:
        signal_analysis[sig_name] = {
            "tp": _signal_group_stats(tp_rows, sig_name),
            "kn": _signal_group_stats(kn_rows, sig_name),
            "separation_score": _separation_score(
                [r["diag_signals"].get(sig_name) for r in tp_rows],
                [r["diag_signals"].get(sig_name) for r in kn_rows],
            ),
        }

    # Pass-level stats
    pass_analysis: dict[str, Any] = {}
    for pass_name in all_pass_names:
        tp_pass = _pass_group_stats(tp_rows, pass_name)
        kn_pass = _pass_group_stats(kn_rows, pass_name)
        tp_rate = tp_pass["matched_rate"] or 0.0
        kn_rate = kn_pass["matched_rate"] or 0.0
        pass_analysis[pass_name] = {
            "tp": tp_pass,
            "kn": kn_pass,
            "separation_score": round(abs(tp_rate - kn_rate), 4) if tp_rows and kn_rows else None,
        }

    # Separating features ranking (numeric + bool features with valid separation scores)
    ranked_features: list[dict[str, Any]] = []
    for name, stats in feature_comparison.items():
        sep = stats.get("separation_score")
        if sep is not None:
            tp_s = stats.get("tp") or {}
            kn_s = stats.get("kn") or {}
            tp_val = tp_s.get("mean") or tp_s.get("rate")
            kn_val = kn_s.get("mean") or kn_s.get("rate")
            ranked_features.append({"feature": name, "separation_score": sep, "tp_value": tp_val, "kn_value": kn_val})
    for sig_name, sig_stats in signal_analysis.items():
        sep = sig_stats.get("separation_score")
        if sep is not None:
            ranked_features.append({
                "feature": f"signal:{sig_name}",
                "separation_score": sep,
                "tp_value": (sig_stats["tp"].get("score_stats") or {}).get("mean"),
                "kn_value": (sig_stats["kn"].get("score_stats") or {}).get("mean"),
            })
    ranked_features.sort(key=lambda x: x["separation_score"], reverse=True)

    return {
        "schema_version": SCHEMA_VERSION,
        "source_csv": str(csv_path),
        "total_rows": total,
        "pure_embedding_count": len(pure_rows),
        "other_candidate_count": len(other_rows_raw),
        "cohort": {
            "tp": len(tp_rows),
            "kn": len(kn_rows),
            "partial": len(partial_rows),
            "unlabeled": len(unlabeled_rows),
        },
        "match_type_breakdown": match_type_counts,
        "stage_breakdown": stage_counts,
        "all_signal_names": all_signal_names,
        "all_pass_names": all_pass_names,
        "feature_comparison": feature_comparison,
        "signal_analysis": signal_analysis,
        "pass_analysis": pass_analysis,
        "separating_features_ranked": ranked_features,
        "pure_embedding_rows": pure_rows,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------

def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _num_row(label: str, tp_stats: dict, kn_stats: dict) -> str:
    return (
        f"| {label} | {_fmt(tp_stats.get('n'))} | {_fmt(tp_stats.get('min'))} | "
        f"{_fmt(tp_stats.get('median'))} | {_fmt(tp_stats.get('mean'))} | {_fmt(tp_stats.get('max'))} | "
        f"{_fmt(kn_stats.get('n'))} | {_fmt(kn_stats.get('min'))} | "
        f"{_fmt(kn_stats.get('median'))} | {_fmt(kn_stats.get('mean'))} | {_fmt(kn_stats.get('max'))} |"
    )


def render_markdown(report: dict[str, Any]) -> str:
    cohort = report.get("cohort") or {}
    fc = report.get("feature_comparison") or {}
    sa = report.get("signal_analysis") or {}
    pa = report.get("pass_analysis") or {}
    ranked = report.get("separating_features_ranked") or []

    lines: list[str] = []
    lines.append("# v0.10.9 Pure Embedding Candidate Diagnostic")
    lines.append("")
    lines.append(f"Source: `{report.get('source_csv')}`")
    lines.append("")

    lines.append("## Cohort Overview")
    lines.append("")
    lines.append(f"- Total rows in candidate_summary.csv: **{report.get('total_rows')}**")
    lines.append(f"- Pure embedding rows (candidate_category=semantic_recall): **{report.get('pure_embedding_count')}**")
    lines.append(f"- Other candidates: **{report.get('other_candidate_count')}**")
    lines.append("")
    lines.append("| Group | Count |")
    lines.append("|---|---:|")
    lines.append(f"| TP (truth_label=duplicate) | **{cohort.get('tp', 0)}** |")
    lines.append(f"| KN (truth_label=not_duplicate) | **{cohort.get('kn', 0)}** |")
    lines.append(f"| Partial overlap | {cohort.get('partial', 0)} |")
    lines.append(f"| Unlabeled | {cohort.get('unlabeled', 0)} |")
    lines.append("")

    # Match type and stage breakdown
    mt = report.get("match_type_breakdown") or {}
    st = report.get("stage_breakdown") or {}
    if mt:
        lines.append("### Match Type Breakdown (pure embedding cohort)")
        lines.append("")
        for k, v in mt.items():
            lines.append(f"- `{k}`: {v}")
        lines.append("")
    if st:
        lines.append("### Stage Breakdown (pure embedding cohort)")
        lines.append("")
        for k, v in st.items():
            lines.append(f"- `{k}`: {v}")
        lines.append("")

    # Numeric feature comparison header
    lines.append("## Feature Comparison: TP vs KN")
    lines.append("")
    lines.append("> Native / Tesseract / OpenAI word counts are not written to candidate_summary.csv.")
    lines.append("> Only best_word_count (the selected final word count) is available here.")
    lines.append("")
    lines.append("### Numeric Features")
    lines.append("")
    lines.append("| Feature | TP n | TP min | TP median | TP mean | TP max | KN n | KN min | KN median | KN mean | KN max |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for feat in ["embedding_confidence", "a_best_word_count", "b_best_word_count", "min_word_count", "combined_word_count"]:
        stats = fc.get(feat) or {}
        lines.append(_num_row(f"`{feat}`", stats.get("tp") or {}, stats.get("kn") or {}))
    lines.append("")

    lines.append("### Boolean / Evidence Features")
    lines.append("")
    lines.append("| Feature | TP rate | TP count | KN rate | KN count | Separation |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    bool_feat_order = [
        "has_supporting_evidence",
        "has_det_pass_matched",
        "has_non_embedding_signal",
        "has_key_token_signal",
        "has_rare_token_signal",
        "has_perceptual_support",
        "has_sequence_signal",
        "same_document",
        "a_tesseract_attempted",
        "b_tesseract_attempted",
        "a_tesseract_usable",
        "b_tesseract_usable",
        "a_openai_ocr_selected",
        "b_openai_ocr_selected",
        "a_low_information",
        "b_low_information",
    ]
    for feat in bool_feat_order:
        stats = fc.get(feat) or {}
        tp_s = stats.get("tp") or {}
        kn_s = stats.get("kn") or {}
        lines.append(
            f"| `{feat}` | {_fmt(tp_s.get('rate'))} | {tp_s.get('count_true', 0)}/{tp_s.get('n', 0)} | "
            f"{_fmt(kn_s.get('rate'))} | {kn_s.get('count_true', 0)}/{kn_s.get('n', 0)} | "
            f"{_fmt(stats.get('separation_score'))} |"
        )
    lines.append("")

    lines.append("### Categorical: Review Bucket")
    lines.append("")
    tp_rb = (fc.get("review_bucket") or {}).get("tp") or {}
    kn_rb = (fc.get("review_bucket") or {}).get("kn") or {}
    all_buckets = sorted(set(list(tp_rb.keys()) + list(kn_rb.keys())))
    lines.append("| Bucket | TP | KN |")
    lines.append("|---|---:|---:|")
    for b in all_buckets:
        lines.append(f"| `{b}` | {tp_rb.get(b, 0)} | {kn_rb.get(b, 0)} |")
    lines.append("")

    lines.append("### Categorical: Text Source")
    lines.append("")
    lines.append("#### a_text_source")
    lines.append("")
    tp_ats = (fc.get("a_text_source") or {}).get("tp") or {}
    kn_ats = (fc.get("a_text_source") or {}).get("kn") or {}
    all_ats = sorted(set(list(tp_ats.keys()) + list(kn_ats.keys())))
    lines.append("| Source | TP | KN |")
    lines.append("|---|---:|---:|")
    for s in all_ats:
        lines.append(f"| `{s}` | {tp_ats.get(s, 0)} | {kn_ats.get(s, 0)} |")
    lines.append("")

    lines.append("#### b_text_source")
    lines.append("")
    tp_bts = (fc.get("b_text_source") or {}).get("tp") or {}
    kn_bts = (fc.get("b_text_source") or {}).get("kn") or {}
    all_bts = sorted(set(list(tp_bts.keys()) + list(kn_bts.keys())))
    lines.append("| Source | TP | KN |")
    lines.append("|---|---:|---:|")
    for s in all_bts:
        lines.append(f"| `{s}` | {tp_bts.get(s, 0)} | {kn_bts.get(s, 0)} |")
    lines.append("")

    # Signal analysis
    if sa:
        lines.append("## Signal Analysis")
        lines.append("")
        lines.append("| Signal | TP presence | TP mean score | KN presence | KN mean score | Separation |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for sig_name in sorted(sa.keys()):
            sig = sa[sig_name]
            tp_s = sig.get("tp") or {}
            kn_s = sig.get("kn") or {}
            tp_score = (tp_s.get("score_stats") or {}).get("mean")
            kn_score = (kn_s.get("score_stats") or {}).get("mean")
            lines.append(
                f"| `{sig_name}` | {_fmt(tp_s.get('presence_rate'))} | {_fmt(tp_score)} | "
                f"{_fmt(kn_s.get('presence_rate'))} | {_fmt(kn_score)} | {_fmt(sig.get('separation_score'))} |"
            )
        lines.append("")

    # Pass analysis
    if pa:
        lines.append("## Deterministic Pass Analysis")
        lines.append("")
        lines.append("| Pass | TP matched rate | KN matched rate | Separation |")
        lines.append("|---|---:|---:|---:|")
        for pass_name in sorted(pa.keys()):
            p = pa[pass_name]
            tp_p = p.get("tp") or {}
            kn_p = p.get("kn") or {}
            lines.append(
                f"| `{pass_name}` | {_fmt(tp_p.get('matched_rate'))} | "
                f"{_fmt(kn_p.get('matched_rate'))} | {_fmt(p.get('separation_score'))} |"
            )
        lines.append("")

    # Separating features ranked
    lines.append("## Separating Features (ranked by |TP - KN|)")
    lines.append("")
    lines.append("| Rank | Feature | Separation | TP value | KN value |")
    lines.append("|---:|---|---:|---:|---:|")
    for i, item in enumerate(ranked[:20], 1):
        lines.append(
            f"| {i} | `{item['feature']}` | {_fmt(item.get('separation_score'))} | "
            f"{_fmt(item.get('tp_value'))} | {_fmt(item.get('kn_value'))} |"
        )
    lines.append("")

    lines.append("---")
    lines.append(f"*Schema: `{report.get('schema_version')}`*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

_FLAT_DIAG_FIELDS = [
    "diag_group",
    "diag_emb_score",
    "diag_has_supporting_evidence",
    "diag_has_det_pass_matched",
    "diag_has_non_embedding_signal",
    "diag_has_key_token_signal",
    "diag_key_token_score",
    "diag_has_rare_token_signal",
    "diag_rare_token_score",
    "diag_has_perceptual_support",
    "diag_perceptual_score",
    "diag_has_sequence_signal",
    "diag_sequence_score",
    "diag_same_document",
    "diag_a_best_word_count",
    "diag_b_best_word_count",
    "diag_min_word_count",
    "diag_combined_word_count",
    "diag_matched_passes",
    "diag_non_embedding_signal_names",
]

_BASE_FIELDS = [
    "rank", "truth_label", "truth_kind", "match_type", "candidate_stage",
    "candidate_category", "review_bucket", "visibility", "confidence",
    "a_document", "a_page", "b_document", "b_page",
    "a_text_source", "b_text_source",
    "a_best_word_count", "b_best_word_count",
    "a_ocr_route", "b_ocr_route",
    "a_tesseract_attempted", "b_tesseract_attempted",
    "a_tesseract_usable", "b_tesseract_usable",
    "a_openai_ocr_selected", "b_openai_ocr_selected",
    "a_low_information", "b_low_information",
    "signals", "deterministic_passes",
]


def write_outputs(report: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON (without per-row data to keep it readable)
    summary = {k: v for k, v in report.items() if k != "pure_embedding_rows"}
    (out_dir / "embedding_diagnostic.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Markdown
    (out_dir / "embedding_diagnostic.md").write_text(render_markdown(report), encoding="utf-8")

    # Tagged CSV with all pure embedding rows + computed columns
    rows = report.get("pure_embedding_rows") or []
    if rows:
        fields = _BASE_FIELDS + _FLAT_DIAG_FIELDS
        with (out_dir / "embedding_diagnostic_rows.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                flat = dict(row)
                if isinstance(flat.get("diag_matched_passes"), list):
                    flat["diag_matched_passes"] = ";".join(flat["diag_matched_passes"])
                if isinstance(flat.get("diag_non_embedding_signal_names"), list):
                    flat["diag_non_embedding_signal_names"] = ";".join(flat["diag_non_embedding_signal_names"])
                writer.writerow({k: flat.get(k, "") for k in fields})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="v0.10.9 offline diagnostic: compare pure embedding TPs vs KNs in candidate_summary.csv"
    )
    parser.add_argument("csv_path", type=Path, help="Path to candidate_summary.csv from a v0.10.8 widened run")
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory (default: csv_path/../embedding_diagnostic)")
    args = parser.parse_args(argv)

    csv_path = args.csv_path
    out_dir = args.out_dir or (csv_path.parent / "embedding_diagnostic")

    report = build_report(csv_path)
    write_outputs(report, out_dir)

    cohort = report.get("cohort") or {}
    print(f"Pure embedding diagnostic written to: {out_dir}")
    print(f"  Total rows: {report.get('total_rows')}")
    print(f"  Pure embedding (semantic_recall): {report.get('pure_embedding_count')}")
    print(f"  TP: {cohort.get('tp', 0)}  KN: {cohort.get('kn', 0)}  Partial: {cohort.get('partial', 0)}  Unlabeled: {cohort.get('unlabeled', 0)}")
    print(f"  - {out_dir / 'embedding_diagnostic.md'}")
    print(f"  - {out_dir / 'embedding_diagnostic.json'}")
    print(f"  - {out_dir / 'embedding_diagnostic_rows.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
