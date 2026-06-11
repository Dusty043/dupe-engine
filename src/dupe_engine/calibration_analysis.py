from __future__ import annotations

import csv
import json
import os
import re
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "dupe_engine_calibration_llm_analysis_v0_10_0"
DEFAULT_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class LlmAnalysisOptions:
    enabled: bool = False
    dry_run: bool = False
    include_text_snippets: bool = False
    model: str | None = None
    base_url: str | None = None
    output_md: str | None = None
    output_json: str | None = None


class CalibrationAnalysisError(RuntimeError):
    pass


def run_calibration_llm_analysis(calibration_dir: Path, options: LlmAnalysisOptions | None = None) -> dict[str, Any]:
    """Write a metrics-only calibration analysis report.

    The default payload intentionally avoids OCR/document text. It summarizes
    calibration manifests, scorecards, recommendations, false-negative reason
    counts, OCR fallback counts, and queue burden so an LLM can produce a useful
    readout without seeing PHI-like extracted content.
    """

    options = options or LlmAnalysisOptions(enabled=True)
    calibration_dir = Path(calibration_dir).resolve()
    if not calibration_dir.exists():
        raise CalibrationAnalysisError(f"Calibration directory does not exist: {calibration_dir}")

    payload = build_analysis_payload(calibration_dir, include_text_snippets=options.include_text_snippets)
    heuristic_report = build_heuristic_report(payload)
    analysis_json_path = Path(options.output_json) if options.output_json else calibration_dir / "llm_analysis.json"
    analysis_md_path = Path(options.output_md) if options.output_md else calibration_dir / "llm_analysis.md"

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "calibration_dir": str(calibration_dir),
        "status": "heuristic_only",
        "provider": "heuristic",
        "model": None,
        "metrics_only": not options.include_text_snippets,
        "input_summary": summarize_payload(payload),
        "heuristic_report": heuristic_report,
        "llm_report": None,
        "raw_llm_response": None,
        "error_message": "",
    }

    report_text = heuristic_report
    if options.dry_run:
        result["status"] = "dry_run"
        result["error_message"] = "LLM analysis dry-run; wrote heuristic report only."
    else:
        provider_result = call_llm_analysis(payload, heuristic_report, options)
        result.update(provider_result)
        report_text = provider_result.get("llm_report") or heuristic_report

    write_json(analysis_json_path, result)
    analysis_md_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_md_path.write_text(report_text.strip() + "\n", encoding="utf-8")
    result["analysis_json"] = str(analysis_json_path)
    result["analysis_md"] = str(analysis_md_path)
    return result


def build_analysis_payload(calibration_dir: Path, *, include_text_snippets: bool = False) -> dict[str, Any]:
    manifest = read_json(calibration_dir / "calibration_manifest.json")
    scorecard = read_json(calibration_dir / "scorecard.json")
    recommendations = read_json(calibration_dir / "recommended_configs.json")
    rows = scorecard.get("rows") or read_scorecard_csv(calibration_dir / "scorecard.csv")
    sanitized_rows = [sanitize_scorecard_row(row) for row in rows]
    run_artifacts = collect_run_artifact_summaries(calibration_dir, include_text_snippets=include_text_snippets)
    return {
        "schema_version": "dupe_engine_calibration_analysis_payload_v0_10_0",
        "metrics_only": not include_text_snippets,
        "calibration_dir_name": calibration_dir.name,
        "manifest": sanitize_manifest(manifest),
        "scorecard_rows": sanitized_rows,
        "recommendations": sanitize_recommendations(recommendations),
        "run_artifacts": run_artifacts,
        "aggregate": build_aggregate_summary(sanitized_rows),
    }


def sanitize_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    runs = []
    for run in manifest.get("runs", []) or []:
        runs.append({
            "run_id": run.get("run_id"),
            "stage": run.get("stage"),
            "corpus_id": run.get("corpus_id"),
            "variant_id": run.get("variant_id"),
            "ocr_cap": run.get("ocr_cap"),
            "ocr_selection_mode": run.get("ocr_selection_mode"),
            "vector_profile": run.get("vector_profile"),
            "queue_profile": run.get("queue_profile"),
            "dpi": run.get("dpi"),
            "strict_tfidf_threshold": run.get("strict_tfidf_threshold"),
            "standard_tfidf_threshold": run.get("standard_tfidf_threshold"),
            "loose_tfidf_threshold": run.get("loose_tfidf_threshold"),
            "multipass_text_top_k": run.get("multipass_text_top_k"),
            "main_review_min_confidence": run.get("main_review_min_confidence"),
            "main_review_max_candidates_per_100_pages": run.get("main_review_max_candidates_per_100_pages"),
            "sequence_anchor_min_confidence": run.get("sequence_anchor_min_confidence"),
            "sequence_min_text_similarity": run.get("sequence_min_text_similarity"),
            "sequence_min_text_similarity_with_visual": run.get("sequence_min_text_similarity_with_visual"),
            "cross_view_text_candidates_enabled": run.get("cross_view_text_candidates_enabled"),
            "rare_token_candidates_enabled": run.get("rare_token_candidates_enabled"),
            "rare_token_min_overlap": run.get("rare_token_min_overlap"),
            "rare_token_min_jaccard": run.get("rare_token_min_jaccard"),
            "rare_token_max_df": run.get("rare_token_max_df"),
            "post_candidate_rescue_pages": run.get("post_candidate_rescue_pages"),
            "ocr_evidence_upgrade_enabled": run.get("ocr_evidence_upgrade_enabled"),
            "embedding_hybrid_scoring": run.get("embedding_hybrid_scoring"),
        })
    corpora = []
    for corpus in manifest.get("corpora", []) or []:
        corpora.append({
            "corpus_id": corpus.get("corpus_id"),
            "pdf_dir_name": Path(str(corpus.get("pdf_dir") or "")).name,
            "truth_name": Path(str(corpus.get("truth") or "")).name,
        })
    return {
        "schema_version": manifest.get("schema_version"),
        "profile": manifest.get("profile"),
        "planned_run_count": manifest.get("planned_run_count"),
        "stages": manifest.get("stages"),
        "corpora": corpora,
        "runs": runs,
    }


def sanitize_scorecard_row(row: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "run_id", "stage", "profile_name", "corpus_id", "variant_id", "dpi",
        "ocr_evidence_upgrade_enabled", "strict_tfidf_threshold", "standard_tfidf_threshold",
        "loose_tfidf_threshold", "multipass_text_top_k", "max_candidates_per_job",
        "max_candidates_per_page", "main_review_min_confidence",
        "main_review_max_candidates_per_100_pages", "openai_ocr_min_candidate_confidence",
        "openai_ocr_max_pages_per_document", "sequence_anchor_min_confidence", "sequence_neighbor_window", "sequence_min_text_similarity",
        "sequence_min_text_similarity_with_visual", "sequence_visual_support_phash_threshold",
        "cross_view_text_candidates_enabled", "rare_token_candidates_enabled", "rare_token_min_overlap",
        "rare_token_min_jaccard", "rare_token_max_df",
        "ocr_cap", "ocr_selection_mode", "openai_ocr_selected",
        "openai_ocr_attempted", "openai_ocr_usable", "openai_ocr_improved",
        "openai_ocr_eligible_skipped", "embeddings_enabled", "embedding_profile", "embedding_top_k",
        "embedding_min_similarity", "embedding_min_margin", "embedding_max_candidates_per_page",
        "embedding_max_candidates_per_job", "embedding_min_text_chars", "embedding_candidates", "embedding_calls",
        "queue_profile", "post_candidate_rescue_pages", "embedding_hybrid_scoring",
        "openai_ocr_selection_reason_counts", "false_negative_reason_counts", "strict_recall",
        "any_queue_recall", "main_review_recall", "main_or_secondary_recall", "secondary_review_recall",
        "ocr_dependent_recall", "ocr_ready_pair_rate", "vector_recall_at_5", "vector_group_recall_at_5",
        "true_positives", "false_negatives", "known_negative_hits", "unknown_predictions",
        "main_queue_size", "secondary_queue_size", "calibration_queue_size", "candidates_per_100_pages",
        "runtime_seconds", "status", "reviewable_score", "error_message",
    ]
    sanitized = {key: coerce_value(row.get(key)) for key in keys if key in row}
    # Normalize JSON-like count fields for easier prompting.
    for key in ["openai_ocr_selection_reason_counts", "false_negative_reason_counts"]:
        if key in sanitized and isinstance(sanitized[key], str):
            sanitized[key] = parse_jsonish(sanitized[key])
    return sanitized


def sanitize_recommendations(recommendations: dict[str, Any]) -> dict[str, Any]:
    recs = recommendations.get("recommendations") or {}
    sanitized_recs: dict[str, Any] = {}
    for key, value in recs.items():
        if isinstance(value, dict):
            sanitized_recs[key] = sanitize_scorecard_row(value) if "run_id" in value else value
        else:
            sanitized_recs[key] = value
    generalization = recommendations.get("generalization_summary") or {}
    return {
        "schema_version": recommendations.get("schema_version"),
        "recommendations": sanitized_recs,
        "generalization_summary": generalization,
        "notes": recommendations.get("notes"),
    }


def collect_run_artifact_summaries(calibration_dir: Path, *, include_text_snippets: bool = False) -> list[dict[str, Any]]:
    runs_dir = calibration_dir / "runs"
    if not runs_dir.exists():
        return []
    summaries: list[dict[str, Any]] = []
    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        status = read_json(run_dir / "run_status.json")
        truth_eval = read_json(run_dir / "truth_eval.json")
        phase_eval = read_json(run_dir / "phase_eval.json")
        fallback = read_json(run_dir / "fallback_audit.json")
        summary = {
            "run_id": run_dir.name,
            "status": status.get("status"),
            "stage": status.get("stage"),
            "corpus_id": status.get("corpus_id"),
            "variant_id": status.get("variant_id"),
            "truth_summary": truth_eval.get("summary", {}),
            "fallback_summary": fallback.get("summary", {}),
            "review_queue_summary": ((phase_eval.get("review_queue_eval") or {}).get("summary") or {}),
            "ocr_rescue_summary": ((phase_eval.get("ocr_rescue_eval") or {}).get("summary") or {}),
            "vector_summary": ((phase_eval.get("vector_retrieval_eval") or {}).get("summary") or {}),
        }
        fn_path = run_dir / "false_negatives.csv"
        summary["false_negative_reason_counts"] = count_csv_values(fn_path, "reason_missed")
        if include_text_snippets:
            summary["false_negative_sample_metadata"] = read_false_negative_metadata(fn_path, limit=5)
        summaries.append(summary)
    return summaries


def build_aggregate_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    succeeded = [row for row in rows if row.get("status") == "succeeded"]
    by_corpus: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_variant: dict[str, list[dict[str, Any]]] = defaultdict(list)
    fn_counts: Counter[str] = Counter()
    selection_counts: Counter[str] = Counter()
    for row in succeeded:
        by_corpus[str(row.get("corpus_id") or "unknown")].append(row)
        by_variant[str(row.get("variant_id") or row.get("run_id") or "default")].append(row)
        fn_counts.update(row.get("false_negative_reason_counts") or {})
        selection_counts.update(row.get("openai_ocr_selection_reason_counts") or {})
    return {
        "succeeded_run_count": len(succeeded),
        "failed_run_count": len(rows) - len(succeeded),
        "best_by_strict_recall": best_row(rows, "strict_recall"),
        "best_by_reviewable_score": best_row(rows, "reviewable_score"),
        "worst_case_by_variant": summarize_variants(by_variant),
        "corpus_summary": {corpus: summarize_rows(group) for corpus, group in by_corpus.items()},
        "false_negative_reason_counts_total": dict(fn_counts),
        "openai_ocr_selection_reason_counts_total": dict(selection_counts),
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "run_count": len(rows),
        "best_strict_recall": max((floatish(row.get("strict_recall")) for row in rows), default=0.0),
        "avg_strict_recall": round(sum(floatish(row.get("strict_recall")) for row in rows) / max(1, len(rows)), 4),
        "avg_ocr_dependent_recall": round(sum(floatish(row.get("ocr_dependent_recall")) for row in rows) / max(1, len(rows)), 4),
        "avg_unknown_predictions": round(sum(floatish(row.get("unknown_predictions")) for row in rows) / max(1, len(rows)), 2),
    }


def summarize_variants(grouped: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    items = []
    for variant, rows in grouped.items():
        strict = [floatish(row.get("strict_recall")) for row in rows]
        items.append({
            "variant_id": variant,
            "run_count": len(rows),
            "avg_strict_recall": round(sum(strict) / max(1, len(strict)), 4),
            "worst_strict_recall": round(min(strict), 4) if strict else 0.0,
            "corpora": sorted({str(row.get("corpus_id") or "unknown") for row in rows}),
        })
    items.sort(key=lambda item: (item["worst_strict_recall"], item["avg_strict_recall"]), reverse=True)
    return items


def build_heuristic_report(payload: dict[str, Any]) -> str:
    aggregate = payload.get("aggregate", {})
    recommendations = payload.get("recommendations", {})
    best = (((recommendations.get("recommendations") or {}).get("best_generalized_config"))
            or ((recommendations.get("recommendations") or {}).get("best_by_recall_first_score"))
            or aggregate.get("best_by_strict_recall")
            or {})
    fn_counts = aggregate.get("false_negative_reason_counts_total") or {}
    selection_counts = aggregate.get("openai_ocr_selection_reason_counts_total") or {}
    corpus_summary = aggregate.get("corpus_summary") or {}
    variants = aggregate.get("worst_case_by_variant") or []
    primary_bottleneck = max(fn_counts.items(), key=lambda item: item[1], default=("unknown", 0))[0]

    lines = [
        "# Calibration Analysis Report",
        "",
        "## Executive summary",
        f"- Best apparent config: `{best.get('run_id') or best.get('variant_id') or 'unknown'}`.",
        f"- Primary bottleneck from false-negative counts: `{primary_bottleneck}`.",
        f"- Succeeded runs: {aggregate.get('succeeded_run_count', 0)}; failed runs: {aggregate.get('failed_run_count', 0)}.",
        "- This report is metrics-only by default; raw OCR/document text is not included.",
        "",
        "## Corpus readout",
    ]
    for corpus, summary in corpus_summary.items():
        lines.append(
            f"- `{corpus}`: best strict recall {summary.get('best_strict_recall')}, "
            f"average strict recall {summary.get('avg_strict_recall')}, "
            f"average OCR-dependent recall {summary.get('avg_ocr_dependent_recall')}."
        )
    if variants:
        lines.extend(["", "## Generalization readout"])
        for item in variants[:5]:
            lines.append(
                f"- `{item.get('variant_id')}`: avg recall {item.get('avg_strict_recall')}, "
                f"worst-case recall {item.get('worst_strict_recall')}, corpora {', '.join(item.get('corpora') or [])}."
            )
    lines.extend([
        "",
        "## OCR/fallback diagnosis",
        f"- OpenAI OCR selection reason totals: `{json.dumps(selection_counts, sort_keys=True)}`.",
        f"- False-negative reason totals: `{json.dumps(fn_counts, sort_keys=True)}`.",
    ])
    if primary_bottleneck == "fallback_selected_but_still_weak":
        lines.append("- Interpretation: pages are being selected for fallback, but fallback evidence is still not strong enough downstream. More page budget alone is unlikely to solve this.")
    elif primary_bottleneck == "fallback_not_selected":
        lines.append("- Interpretation: fallback selection/budget still appears to miss important pages. Test selection expansion before deeper adjudication layers.")
    elif "deterministic" in primary_bottleneck:
        lines.append("- Interpretation: usable evidence may exist, but candidate generation/thresholding is not surfacing enough pairs.")
    lines.extend([
        "",
        "## Recommended next experiments",
        "1. Focus on the dominant false-negative bucket rather than running a broad matrix.",
        "2. Compare one baseline against one targeted fix across both corpora.",
        "3. Avoid retrying configs that increase queue burden without raising worst-case recall.",
        "",
        "## Do not over-interpret",
        "- This report summarizes calibration artifacts; it does not inspect raw page images or OCR text unless explicitly configured.",
        "- Treat recommendations as planning support, not autonomous model changes.",
    ])
    return "\n".join(lines)


def call_llm_analysis(payload: dict[str, Any], heuristic_report: str, options: LlmAnalysisOptions) -> dict[str, Any]:
    api_key = get_analysis_api_key()
    model = options.model or os.getenv("DUPE_LLM_ANALYSIS_MODEL") or os.getenv("DUPE_LLM_MODEL") or DEFAULT_MODEL
    base_url = (options.base_url or os.getenv("DUPE_LLM_ANALYSIS_BASE_URL") or os.getenv("DUPE_LLM_BASE_URL") or os.getenv("DUPE_OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
    if not api_key:
        return {
            "status": "skipped_no_api_key",
            "provider": "openai-compatible",
            "model": model,
            "llm_report": None,
            "raw_llm_response": None,
            "error_message": "LLM analysis API key not configured; set DUPE_LLM_ANALYSIS_API_KEY, DUPE_LLM_API_KEY, DUPE_OPENAI_API_KEY, or OPENAI_API_KEY.",
        }
    prompt = build_llm_prompt(payload, heuristic_report)
    request_body = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You analyze calibration results for a PDF duplicate checker. "
                    "The product goal is high recall with controlled review burden. "
                    "False negatives are more harmful than false positives because humans review candidates. "
                    "Use only the provided metrics. Do not claim production readiness unless metrics support it. "
                    "Return a concise Markdown report with clear next experiments and what not to retry."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    data = json.dumps(request_body).encode("utf-8")
    request = urllib.request.Request(
        url=f"{base_url}/chat/completions",
        data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=int(os.getenv("DUPE_LLM_ANALYSIS_TIMEOUT_SECONDS", "90"))) as response:
            body = json.loads(response.read().decode("utf-8"))
        report = ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        if not report.strip():
            report = heuristic_report
        return {
            "status": "succeeded",
            "provider": "openai-compatible",
            "model": model,
            "llm_report": report,
            "raw_llm_response": sanitize_llm_response_metadata(body),
            "error_message": "",
        }
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return {
            "status": "failed",
            "provider": "openai-compatible",
            "model": model,
            "llm_report": None,
            "raw_llm_response": None,
            "error_message": f"HTTP {exc.code}: {detail[:500]}",
        }
    except Exception as exc:
        return {
            "status": "failed",
            "provider": "openai-compatible",
            "model": model,
            "llm_report": None,
            "raw_llm_response": None,
            "error_message": str(exc),
        }


def build_llm_prompt(payload: dict[str, Any], heuristic_report: str) -> str:
    compact = compact_payload_for_prompt(payload)
    return (
        "Analyze this calibration result. Focus on generalization, recall, OCR/fallback bottlenecks, vector/embedding behavior, "
        "known-negative pressure, and review burden. Recommend the next 2-3 focused experiments and explicitly list things not worth retrying yet.\n\n"
        "Heuristic report draft:\n"
        f"{heuristic_report}\n\n"
        "Metrics payload JSON:\n"
        f"```json\n{json.dumps(compact, indent=2, default=str)[:45000]}\n```"
    )


def compact_payload_for_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("scorecard_rows") or []
    compact_rows = []
    for row in rows:
        compact_rows.append({
            key: row.get(key)
            for key in [
                "run_id", "corpus_id", "variant_id", "ocr_cap", "dpi", "ocr_evidence_upgrade_enabled",
                "strict_tfidf_threshold", "standard_tfidf_threshold", "loose_tfidf_threshold",
                "multipass_text_top_k", "main_review_min_confidence", "main_review_max_candidates_per_100_pages",
                "openai_ocr_max_pages_per_document", "sequence_anchor_min_confidence", "sequence_min_text_similarity", "sequence_min_text_similarity_with_visual",
                "cross_view_text_candidates_enabled", "rare_token_candidates_enabled", "rare_token_min_overlap", "rare_token_min_jaccard",
                "embedding_profile", "embedding_top_k", "embedding_min_similarity", "embedding_min_margin",
                "embedding_max_candidates_per_page", "embedding_max_candidates_per_job", "queue_profile", "post_candidate_rescue_pages", "strict_recall",
                "main_or_secondary_recall", "ocr_dependent_recall", "true_positives", "false_negatives",
                "known_negative_hits", "unknown_predictions", "main_queue_size", "secondary_queue_size",
                "openai_ocr_selected", "openai_ocr_usable", "openai_ocr_eligible_skipped",
                "openai_ocr_selection_reason_counts", "false_negative_reason_counts", "reviewable_score",
            ]
            if key in row
        })
    return {
        "metrics_only": payload.get("metrics_only"),
        "manifest": payload.get("manifest"),
        "scorecard_rows": compact_rows,
        "recommendations": payload.get("recommendations"),
        "aggregate": payload.get("aggregate"),
    }


def get_analysis_api_key() -> str | None:
    env_name = os.getenv("DUPE_LLM_ANALYSIS_API_KEY_ENV", "").strip()
    candidates = [env_name, "DUPE_LLM_ANALYSIS_API_KEY", "DUPE_LLM_API_KEY", os.getenv("DUPE_OPENAI_API_KEY_ENV", ""), "DUPE_OPENAI_API_KEY", "OPENAI_API_KEY"]
    seen = set()
    for name in candidates:
        if not name or name in seen:
            continue
        seen.add(name)
        value = os.getenv(name)
        if value:
            return value
    return None


def sanitize_llm_response_metadata(body: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": body.get("id"),
        "model": body.get("model"),
        "usage": body.get("usage"),
        "finish_reason": (((body.get("choices") or [{}])[0]) or {}).get("finish_reason"),
    }


def summarize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("scorecard_rows") or []
    return {
        "calibration_dir_name": payload.get("calibration_dir_name"),
        "profile": (payload.get("manifest") or {}).get("profile"),
        "run_count": len(rows),
        "corpora": [corpus.get("corpus_id") for corpus in ((payload.get("manifest") or {}).get("corpora") or [])],
        "metrics_only": payload.get("metrics_only"),
    }


def best_row(rows: list[dict[str, Any]], key: str) -> dict[str, Any] | None:
    good = [row for row in rows if row.get("status") in {None, "succeeded"}]
    return max(good, key=lambda row: floatish(row.get(key)), default=None)


def count_csv_values(path: Path, column: str) -> dict[str, int]:
    if not path.exists():
        return {}
    counts: Counter[str] = Counter()
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                value = row.get(column) or "unknown"
                counts[value] += 1
    except Exception:
        return {}
    return dict(counts)


def read_false_negative_metadata(path: Path, limit: int = 5) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    allowed = [
        "pair_id", "truth_label", "expected_min_layer", "left_file", "left_page", "right_file", "right_page",
        "left_text_source", "right_text_source", "left_ocr_route", "right_ocr_route", "reason_missed",
        "recommended_action", "embedding_rank", "embedding_similarity", "deterministic_best_score",
    ]
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rows.append({key: row.get(key) for key in allowed if key in row})
                if len(rows) >= limit:
                    break
    except Exception:
        return []
    return rows


def read_scorecard_csv(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def parse_jsonish(value: str) -> Any:
    value = value.strip()
    if not value:
        return {}
    try:
        return json.loads(value)
    except Exception:
        return value


def coerce_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (int, float, bool, dict, list)):
        return value
    text = str(value)
    if text.lower() in {"true", "false"}:
        return text.lower() == "true"
    if text == "":
        return None
    if re.fullmatch(r"-?\d+", text):
        try:
            return int(text)
        except Exception:
            return text
    if re.fullmatch(r"-?\d+\.\d+", text):
        try:
            return float(text)
        except Exception:
            return text
    return text


def floatish(value: Any) -> float:
    try:
        if value in {None, ""}:
            return 0.0
        return float(value)
    except Exception:
        return 0.0
