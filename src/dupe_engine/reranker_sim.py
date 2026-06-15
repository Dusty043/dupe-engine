"""v0.10.9 offline reranker simulation.

Reads candidate_summary.csv and simulates the precision reranker over the
pure embedding cohort to estimate TP/KN action rates at each threshold value.

Imports score_components and RerankerParams from embedding_reranker (no math
duplication). Reuses IO and classification helpers from embedding_diagnostic.

Usage:
    from dupe_engine.reranker_sim import simulate, write_outputs
    result = simulate(csv_path, params, thresholds)
    write_outputs(result, out_dir)
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .embedding_reranker import RerankerParams, score_components
from .embedding_diagnostic import (
    _as_bool,
    _as_float,
    _as_int,
    _read_csv,
)

SCHEMA_VERSION = "dupe_engine_reranker_sim_v0_10_9"

GROUP_TP = "tp"
GROUP_KN = "kn"
GROUP_PARTIAL = "partial"
GROUP_UNLABELED = "unlabeled"

_DEFAULT_THRESHOLDS: list[float] = [0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94]

_DEMOTE_SEMANTICS_WARNING = """\
### Demote Semantics Warning

Demotion lowers confidence to 0.49 and routes matches to calibration-only visibility.
Under **demote** semantics, actioned rows **remain in artifacts** but leave the normal review queue.

**IMPORTANT**: If the evaluator (`truth_eval`) still counts calibration-only / demoted rows
as hits at threshold=0.0, `expected_negative_hit_count` may not improve under demote semantics.

The row-level impact shown above reflects review-visible impact only.

To guarantee a reduction in `expected_negative_hit_count`, use **drop** semantics instead.
"""


# ---------------------------------------------------------------------------
# Row helpers
# ---------------------------------------------------------------------------

def _classify_group(row: dict[str, str]) -> str:
    label = str(row.get("truth_label") or "").strip().lower()
    if label in {"duplicate", "true_positive"}:
        return GROUP_TP
    if label in {"not_duplicate", "known_negative"}:
        return GROUP_KN
    if label in {"partial_overlap"}:
        return GROUP_PARTIAL
    return GROUP_UNLABELED


def _is_pure_embedding_row(row: dict[str, str]) -> bool:
    return str(row.get("match_type") or "").strip() == "embedding_similarity_candidate"


def _score_row(row: dict[str, str], params: RerankerParams) -> tuple[float, dict[str, Any]]:
    confidence = _as_float(row.get("confidence"), 0.0) or 0.0
    a_ocr = _as_bool(row.get("a_openai_ocr_selected"), False)
    b_ocr = _as_bool(row.get("b_openai_ocr_selected"), False)
    a_tess = _as_bool(row.get("a_tesseract_usable"), False)
    b_tess = _as_bool(row.get("b_tesseract_usable"), False)
    a_doc = str(row.get("a_document") or "")
    b_doc = str(row.get("b_document") or "")
    same_doc = bool(a_doc and a_doc == b_doc)
    return score_components(
        confidence=confidence,
        a_ocr=a_ocr,
        b_ocr=b_ocr,
        a_tesseract=a_tess,
        b_tesseract=b_tess,
        same_doc=same_doc,
        params=params,
    )


def enrich_sim_row(row: dict[str, str], params: RerankerParams) -> dict[str, Any]:
    """Return a copy of row with sim scoring columns added."""
    group = _classify_group(row)
    precision_score, components = _score_row(row, params)
    enriched: dict[str, Any] = dict(row)
    enriched.update({
        "sim_group": group,
        "sim_precision_score": round(precision_score, 4),
        "sim_base_confidence": components["base_confidence"],
        "sim_ocr_penalty_total": components["ocr_penalty_total"],
        "sim_tesseract_bonus_total": components["tesseract_bonus_total"],
        "sim_same_document_bonus": components["same_document_bonus"],
        "sim_a_ocr": components["a_openai_ocr_selected"],
        "sim_b_ocr": components["b_openai_ocr_selected"],
        "sim_a_tess": components["a_tesseract_usable"],
        "sim_b_tess": components["b_tesseract_usable"],
        "sim_same_doc": components["same_document"],
        "sim_decision": "",  # filled later at recommended threshold
    })
    return enriched


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def simulate_at_threshold(enriched_rows: list[dict[str, Any]], threshold: float) -> dict[str, Any]:
    """Compute cohort-level action stats at a single threshold value."""
    buckets: dict[str, dict[str, int]] = {
        GROUP_TP: {"kept": 0, "actioned": 0},
        GROUP_KN: {"kept": 0, "actioned": 0},
        GROUP_PARTIAL: {"kept": 0, "actioned": 0},
        GROUP_UNLABELED: {"kept": 0, "actioned": 0},
    }
    for row in enriched_rows:
        g = row["sim_group"]
        bucket = buckets.get(g, buckets[GROUP_UNLABELED])
        if row["sim_precision_score"] < threshold:
            bucket["actioned"] += 1
        else:
            bucket["kept"] += 1

    tp = buckets[GROUP_TP]
    kn = buckets[GROUP_KN]
    partial = buckets[GROUP_PARTIAL]
    unlabeled = buckets[GROUP_UNLABELED]

    tp_total = tp["kept"] + tp["actioned"]
    kn_total = kn["kept"] + kn["actioned"]
    partial_total = partial["kept"] + partial["actioned"]
    unlabeled_total = unlabeled["kept"] + unlabeled["actioned"]
    estimated_removed = tp["actioned"] + kn["actioned"] + partial["actioned"] + unlabeled["actioned"]

    return {
        "threshold": round(threshold, 4),
        "tp_total": tp_total,
        "tp_kept": tp["kept"],
        "tp_demoted_or_dropped": tp["actioned"],
        "tp_action_rate": round(tp["actioned"] / tp_total, 4) if tp_total > 0 else 0.0,
        "kn_total": kn_total,
        "kn_kept": kn["kept"],
        "kn_demoted_or_dropped": kn["actioned"],
        "kn_action_rate": round(kn["actioned"] / kn_total, 4) if kn_total > 0 else 0.0,
        "partial_total": partial_total,
        "partial_kept": partial["kept"],
        "partial_demoted_or_dropped": partial["actioned"],
        "unlabeled_total": unlabeled_total,
        "unlabeled_kept": unlabeled["kept"],
        "unlabeled_demoted_or_dropped": unlabeled["actioned"],
        "estimated_review_rows_removed": estimated_removed,
    }


def threshold_sweep(
    enriched_rows: list[dict[str, Any]],
    thresholds: list[float],
) -> list[dict[str, Any]]:
    return [simulate_at_threshold(enriched_rows, t) for t in thresholds]


def recommend_threshold(sweep_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Pick threshold maximizing KN action rate while TP action rate <= 10%."""
    eligible = [r for r in sweep_results if r["tp_action_rate"] <= 0.10]
    if not eligible:
        # Fallback: best TP action rate / KN tradeoff even over 10%
        return min(
            sweep_results,
            key=lambda r: (r["tp_action_rate"], -r["kn_action_rate"], r["threshold"]),
        )
    # Maximize KN action rate; tie-break: lower TP rate, fewer unlabeled kept, lower threshold
    eligible.sort(key=lambda r: (
        -r["kn_action_rate"],
        r["tp_action_rate"],
        r["unlabeled_kept"],
        r["threshold"],
    ))
    return eligible[0]


# ---------------------------------------------------------------------------
# Top-level simulate
# ---------------------------------------------------------------------------

def simulate(
    csv_path: Path,
    params: RerankerParams,
    thresholds: list[float] | None = None,
) -> dict[str, Any]:
    """Run the full offline simulation and return a result dict."""
    thresholds = thresholds or _DEFAULT_THRESHOLDS
    csv_path = csv_path.resolve()

    all_rows = _read_csv(csv_path)
    pure_rows_raw = [r for r in all_rows if _is_pure_embedding_row(r)]
    non_pure_count = len(all_rows) - len(pure_rows_raw)

    # Warn if common bool fields are missing
    missing_warnings: list[str] = []
    for field in ("a_openai_ocr_selected", "b_openai_ocr_selected", "a_tesseract_usable", "b_tesseract_usable"):
        if pure_rows_raw and str(pure_rows_raw[0].get(field) or "").strip() == "":
            missing_warnings.append(field)

    enriched = [enrich_sim_row(r, params) for r in pure_rows_raw]

    cohort = {
        GROUP_TP: sum(1 for r in enriched if r["sim_group"] == GROUP_TP),
        GROUP_KN: sum(1 for r in enriched if r["sim_group"] == GROUP_KN),
        GROUP_PARTIAL: sum(1 for r in enriched if r["sim_group"] == GROUP_PARTIAL),
        GROUP_UNLABELED: sum(1 for r in enriched if r["sim_group"] == GROUP_UNLABELED),
    }

    sweep = threshold_sweep(enriched, thresholds)
    recommended = recommend_threshold(sweep)
    rec_threshold = recommended["threshold"]

    # Tag each enriched row with its decision at the recommended threshold
    for row in enriched:
        row["sim_decision"] = "keep" if row["sim_precision_score"] >= rec_threshold else params.action

    # Example actioned rows (up to 10 each)
    actioned_tp = [r for r in enriched if r["sim_group"] == GROUP_TP and r["sim_decision"] != "keep"][:10]
    actioned_kn = [r for r in enriched if r["sim_group"] == GROUP_KN and r["sim_decision"] != "keep"][:10]

    return {
        "schema_version": SCHEMA_VERSION,
        "source_csv": str(csv_path),
        "params": {
            "min_confidence": params.min_confidence,
            "ocr_penalty": params.ocr_penalty,
            "same_doc_bonus": params.same_doc_bonus,
            "tesseract_bonus": params.tesseract_bonus,
            "action": params.action,
        },
        "total_rows": len(all_rows),
        "pure_embedding_count": len(pure_rows_raw),
        "non_pure_count": non_pure_count,
        "cohort": cohort,
        "thresholds": thresholds,
        "sweep": sweep,
        "recommended": recommended,
        "missing_field_warnings": missing_warnings,
        "enriched_rows": enriched,
        "actioned_tp_examples": actioned_tp,
        "actioned_kn_examples": actioned_kn,
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


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100:.1f}%"


def render_markdown(result: dict[str, Any]) -> str:
    cohort = result.get("cohort") or {}
    params = result.get("params") or {}
    sweep = result.get("sweep") or []
    recommended = result.get("recommended") or {}
    warnings = result.get("missing_field_warnings") or []
    tp_examples = result.get("actioned_tp_examples") or []
    kn_examples = result.get("actioned_kn_examples") or []

    lines: list[str] = []
    lines.append("# v0.10.9 Reranker Offline Simulation")
    lines.append("")
    lines.append(f"Source: `{result.get('source_csv')}`")
    lines.append("")

    lines.append("## Parameters")
    lines.append("")
    lines.append(f"- action: **{params.get('action')}**")
    lines.append(f"- min_confidence (default threshold): **{params.get('min_confidence')}**")
    lines.append(f"- ocr_penalty: {params.get('ocr_penalty')}")
    lines.append(f"- same_doc_bonus: {params.get('same_doc_bonus')}")
    lines.append(f"- tesseract_bonus: {params.get('tesseract_bonus')}")
    lines.append("")

    if warnings:
        lines.append("## Data Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- `{w}` missing or empty in first row — defaulting to False")
        lines.append("")

    lines.append("## Cohort Overview")
    lines.append("")
    lines.append(f"- Total rows in candidate_summary.csv: **{result.get('total_rows')}**")
    lines.append(f"- Pure embedding rows (match_type=embedding_similarity_candidate): **{result.get('pure_embedding_count')}**")
    lines.append(f"- Non-pure rows (untouched by reranker): **{result.get('non_pure_count')}**")
    lines.append("")
    lines.append("| Group | Count |")
    lines.append("|---|---:|")
    lines.append(f"| TP (truth_label=duplicate) | **{cohort.get('tp', 0)}** |")
    lines.append(f"| KN (truth_label=not_duplicate) | **{cohort.get('kn', 0)}** |")
    lines.append(f"| Partial overlap | {cohort.get('partial', 0)} |")
    lines.append(f"| Unlabeled | {cohort.get('unlabeled', 0)} |")
    lines.append("")

    lines.append("## Recommendation")
    lines.append("")
    if recommended:
        rec_tp_rate = _pct(recommended.get("tp_action_rate"))
        rec_kn_rate = _pct(recommended.get("kn_action_rate"))
        lines.append(f"- Recommended threshold: **{recommended.get('threshold')}**")
        lines.append(f"- Action: **{params.get('action')}**")
        lines.append(f"- TP actioned: {recommended.get('tp_demoted_or_dropped')}/{recommended.get('tp_total')} ({rec_tp_rate})")
        lines.append(f"- KN actioned: {recommended.get('kn_demoted_or_dropped')}/{recommended.get('kn_total')} ({rec_kn_rate})")
        lines.append(f"- Estimated review rows removed: {recommended.get('estimated_review_rows_removed')}")
    lines.append("")

    lines.append("## Threshold Sweep")
    lines.append("")
    lines.append("| Threshold | TP total | TP actioned | TP action% | KN total | KN actioned | KN action% | Partial actioned | Unlabeled actioned | Est. removed |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in sweep:
        rec_marker = " ◀" if row["threshold"] == (recommended.get("threshold")) else ""
        lines.append(
            f"| {row['threshold']:.2f}{rec_marker} "
            f"| {row['tp_total']} | {row['tp_demoted_or_dropped']} | {_pct(row['tp_action_rate'])} "
            f"| {row['kn_total']} | {row['kn_demoted_or_dropped']} | {_pct(row['kn_action_rate'])} "
            f"| {row['partial_demoted_or_dropped']} | {row['unlabeled_demoted_or_dropped']} "
            f"| {row['estimated_review_rows_removed']} |"
        )
    lines.append("")

    lines.append("## Drop Semantics Summary")
    lines.append("")
    lines.append("Under **drop** semantics, actioned rows are removed from the returned match list.")
    lines.append("")
    if recommended:
        lines.append(f"At threshold **{recommended.get('threshold')}**:")
        tp_dropped = recommended.get("tp_demoted_or_dropped", 0)
        tp_total = recommended.get("tp_total", 0)
        kn_dropped = recommended.get("kn_demoted_or_dropped", 0)
        lines.append(f"- TPs dropped: {tp_dropped} / {tp_total} ({_pct(recommended.get('tp_action_rate'))})")
        lines.append(f"- KNs dropped: {kn_dropped} / {recommended.get('kn_total', 0)} ({_pct(recommended.get('kn_action_rate'))})")
        lines.append(f"- Partial dropped: {recommended.get('partial_demoted_or_dropped', 0)}")
        lines.append(f"- Unlabeled dropped: {recommended.get('unlabeled_demoted_or_dropped', 0)}")
    lines.append("")

    lines.append(_DEMOTE_SEMANTICS_WARNING)

    if tp_examples:
        lines.append("## Actioned TP Examples (would be affected at recommended threshold)")
        lines.append("")
        lines.append("| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |")
        lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
        for r in tp_examples:
            lines.append(
                f"| {r.get('a_document', '')} | {r.get('a_page', '')} "
                f"| {r.get('b_document', '')} | {r.get('b_page', '')} "
                f"| {_fmt(r.get('sim_base_confidence'))} | {_fmt(r.get('sim_precision_score'))} "
                f"| {r.get('sim_a_ocr')} | {r.get('sim_b_ocr')} "
                f"| {r.get('sim_a_tess')} | {r.get('sim_same_doc')} |"
            )
        lines.append("")

    if kn_examples:
        lines.append("## Actioned KN Examples (would be affected at recommended threshold)")
        lines.append("")
        lines.append("| a_document | a_page | b_document | b_page | confidence | precision_score | a_ocr | b_ocr | a_tess | same_doc |")
        lines.append("|---|---:|---|---:|---:|---:|---:|---:|---:|---:|")
        for r in kn_examples:
            lines.append(
                f"| {r.get('a_document', '')} | {r.get('a_page', '')} "
                f"| {r.get('b_document', '')} | {r.get('b_page', '')} "
                f"| {_fmt(r.get('sim_base_confidence'))} | {_fmt(r.get('sim_precision_score'))} "
                f"| {r.get('sim_a_ocr')} | {r.get('sim_b_ocr')} "
                f"| {r.get('sim_a_tess')} | {r.get('sim_same_doc')} |"
            )
        lines.append("")

    lines.append("---")
    lines.append(f"*Schema: `{result.get('schema_version')}`*")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

_SIM_ROW_FIELDS = [
    "truth_label", "match_type", "candidate_category", "candidate_stage",
    "confidence", "a_document", "a_page", "b_document", "b_page",
    "a_text_source", "b_text_source", "review_bucket", "visibility",
    "a_openai_ocr_selected", "b_openai_ocr_selected",
    "a_tesseract_usable", "b_tesseract_usable",
    # sim columns
    "sim_group",
    "sim_precision_score",
    "sim_base_confidence",
    "sim_ocr_penalty_total",
    "sim_tesseract_bonus_total",
    "sim_same_document_bonus",
    "sim_a_ocr",
    "sim_b_ocr",
    "sim_a_tess",
    "sim_b_tess",
    "sim_same_doc",
    "sim_decision",
]

_SWEEP_FIELDS = [
    "threshold",
    "tp_total", "tp_kept", "tp_demoted_or_dropped", "tp_action_rate",
    "kn_total", "kn_kept", "kn_demoted_or_dropped", "kn_action_rate",
    "partial_total", "partial_kept", "partial_demoted_or_dropped",
    "unlabeled_total", "unlabeled_kept", "unlabeled_demoted_or_dropped",
    "estimated_review_rows_removed",
]


def write_outputs(result: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON (without enriched_rows bulk data)
    summary = {k: v for k, v in result.items() if k not in ("enriched_rows", "actioned_tp_examples", "actioned_kn_examples")}
    (out_dir / "reranker_sim.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    # Markdown
    (out_dir / "reranker_sim.md").write_text(render_markdown(result), encoding="utf-8")

    # Sweep CSV
    sweep = result.get("sweep") or []
    if sweep:
        with (out_dir / "reranker_sim_sweep.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_SWEEP_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in sweep:
                writer.writerow({k: row.get(k, "") for k in _SWEEP_FIELDS})

    # Row-level CSV
    enriched_rows = result.get("enriched_rows") or []
    if enriched_rows:
        with (out_dir / "reranker_sim_rows.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_SIM_ROW_FIELDS, extrasaction="ignore")
            writer.writeheader()
            for row in enriched_rows:
                writer.writerow({k: row.get(k, "") for k in _SIM_ROW_FIELDS})
