from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .calibration_harness import now_iso, write_json

KEEP_SUFFIXES_BY_MODE = {
    "off": set(),
    "analysis-only": {".json", ".jsonl", ".csv", ".md", ".txt"},
    "compact-debug": {".json", ".jsonl", ".csv", ".md", ".txt", ".log"},
}


@dataclass
class GuardrailResult:
    triggered: bool
    stop_reason: str | None
    messages: list[str]
    metrics: dict[str, Any]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except Exception:
        return default


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def free_disk_bytes(path: Path) -> int:
    probe = path if path.exists() else path.parent
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free


def collect_usage_metrics(rows: list[dict[str, Any]], *, out_dir: Path, llm_analysis_calls: int = 0) -> dict[str, Any]:
    openai_ocr_attempted = sum(safe_int(row.get("openai_ocr_attempted")) for row in rows)
    openai_ocr_selected = sum(safe_int(row.get("openai_ocr_selected")) for row in rows)
    embedding_calls = sum(safe_int(row.get("embedding_calls")) for row in rows)
    unknown_predictions = sum(safe_int(row.get("unknown_predictions")) for row in rows if row.get("status") in {None, "succeeded"})
    known_negative_hits = sum(safe_int(row.get("known_negative_hits")) for row in rows if row.get("status") in {None, "succeeded"})
    failed_rows = [row for row in rows if row.get("status") not in {None, "succeeded"}]
    return {
        "row_count": len(rows),
        "failed_row_count": len(failed_rows),
        "openai_ocr_selected": openai_ocr_selected,
        "openai_ocr_attempted": openai_ocr_attempted,
        "embedding_calls": embedding_calls,
        "llm_analysis_calls": llm_analysis_calls,
        "unknown_predictions_total": unknown_predictions,
        "known_negative_hits_total": known_negative_hits,
        "run_dir_bytes": dir_size_bytes(out_dir),
        "run_dir_gb": round(dir_size_bytes(out_dir) / (1024**3), 4),
        "free_disk_gb": round(free_disk_bytes(out_dir) / (1024**3), 4),
    }


def best_group(rows: list[dict[str, Any]], *, target_metric: str, expected_corpus_count: int) -> dict[str, Any] | None:
    from .calibration_loop import rank_variant_groups

    ranked = rank_variant_groups(rows, target_metric=target_metric, expected_corpus_count=expected_corpus_count)
    return ranked[0] if ranked else None


def build_decision_record(
    *,
    iteration: int,
    rows: list[dict[str, Any]],
    iteration_rows: list[dict[str, Any]],
    target_metric: str,
    target_recall: float,
    expected_corpus_count: int,
    previous_best: float | None,
    plateau_count: int,
    accepted: dict[str, Any],
    analysis: dict[str, Any],
    next_variants: list[dict[str, Any]] | None,
    stop_reason: str | None,
    guardrails: dict[str, Any] | None,
    iteration_elapsed_seconds: float,
) -> dict[str, Any]:
    best = best_group(rows, target_metric=target_metric, expected_corpus_count=expected_corpus_count)
    best_metric = safe_float(best.get("worst_metric"), 0.0) if best else 0.0
    gain = None if previous_best is None else round(best_metric - previous_best, 4)
    succeeded = [row for row in iteration_rows if row.get("status") in {None, "succeeded"}]
    failed = [row for row in iteration_rows if row.get("status") not in {None, "succeeded"}]
    record = {
        "schema_version": "dupe_engine_decision_log_v0_10_7",
        "event": "iteration_decision",
        "timestamp": now_iso(),
        "iteration": iteration,
        "target_metric": target_metric,
        "target_recall": target_recall,
        "iteration_elapsed_seconds": round(iteration_elapsed_seconds, 2),
        "iteration_run_count": len(iteration_rows),
        "iteration_succeeded_count": len(succeeded),
        "iteration_failed_count": len(failed),
        "best_variant_id": best.get("variant_id") if best else None,
        "best_avg_metric": best.get("avg_metric") if best else None,
        "best_worst_metric": best.get("worst_metric") if best else None,
        "best_metric_gain": gain,
        "plateau_count": plateau_count,
        "accepted": accepted,
        "stop_reason": stop_reason,
        "guardrails": guardrails or {},
        "analysis_status": analysis.get("status") if isinstance(analysis, dict) else None,
        "analysis_md": analysis.get("analysis_md") if isinstance(analysis, dict) else None,
        "next_variant_ids": [str(variant.get("variant_id")) for variant in (next_variants or [])],
        "decision_summary": decision_summary_text(best=best, gain=gain, accepted=accepted, stop_reason=stop_reason, guardrails=guardrails, next_variants=next_variants),
    }
    return record


def decision_summary_text(*, best: dict[str, Any] | None, gain: float | None, accepted: dict[str, Any], stop_reason: str | None, guardrails: dict[str, Any] | None, next_variants: list[dict[str, Any]] | None) -> str:
    if accepted.get("accepted"):
        candidate = accepted.get("accepted_candidate") or {}
        return f"Accepted {candidate.get('variant_id')} at worst metric {candidate.get('worst_metric')}."
    if stop_reason:
        return f"Stopped with {stop_reason}. Best variant remains {best.get('variant_id') if best else 'none'}."
    if guardrails and guardrails.get("triggered"):
        return f"Guardrail triggered: {guardrails.get('stop_reason')}."
    gain_text = "no previous baseline" if gain is None else f"gain {gain:+.4f}"
    next_count = len(next_variants or [])
    return f"Continue: best={best.get('variant_id') if best else 'none'} worst_metric={best.get('worst_metric') if best else None} ({gain_text}); planned next variants={next_count}."


def evaluate_guardrails(
    args: Any,
    *,
    out_dir: Path,
    all_rows: list[dict[str, Any]],
    started_monotonic: float,
    iteration_elapsed_seconds: float,
    plateau_count: int,
    llm_analysis_calls: int,
    target_metric: str,
    expected_corpus_count: int,
) -> GuardrailResult:
    metrics = collect_usage_metrics(all_rows, out_dir=out_dir, llm_analysis_calls=llm_analysis_calls)
    metrics["total_runtime_seconds"] = round(time.time() - started_monotonic, 2)
    metrics["iteration_elapsed_seconds"] = round(iteration_elapsed_seconds, 2)
    best = best_group(all_rows, target_metric=target_metric, expected_corpus_count=expected_corpus_count)
    metrics["best_variant_id"] = best.get("variant_id") if best else None
    metrics["best_worst_metric"] = best.get("worst_metric") if best else None
    metrics["best_total_unknown_predictions"] = best.get("total_unknown_predictions") if best else None
    metrics["best_total_known_negative_hits"] = best.get("total_known_negative_hits") if best else None
    messages: list[str] = []

    def check_limit(attr: str, metric_key: str, reason: str, scale: float = 1.0) -> str | None:
        value = getattr(args, attr, None)
        if value in {None, ""}:
            return None
        limit = float(value) * scale
        actual = float(metrics.get(metric_key) or 0.0)
        if actual > limit:
            messages.append(f"{metric_key} {actual:.4f} exceeded {limit:.4f}")
            return reason
        return None

    reason = None
    reason = reason or check_limit("max_total_runtime_hours", "total_runtime_seconds", "stopped_runtime_limit", 3600.0)
    reason = reason or check_limit("max_iteration_runtime_hours", "iteration_elapsed_seconds", "stopped_iteration_runtime_limit", 3600.0)
    reason = reason or check_limit("max_run_dir_gb", "run_dir_gb", "paused_storage_limit", 1.0)
    min_free = getattr(args, "min_free_disk_gb", None)
    if reason is None and min_free not in {None, ""}:
        if float(metrics.get("free_disk_gb") or 0.0) < float(min_free):
            messages.append(f"free_disk_gb {metrics.get('free_disk_gb')} below {min_free}")
            reason = "paused_storage_limit"
    reason = reason or check_limit("max_openai_ocr_pages", "openai_ocr_attempted", "paused_cost_limit", 1.0)
    reason = reason or check_limit("max_embedding_calls", "embedding_calls", "paused_cost_limit", 1.0)
    reason = reason or check_limit("max_llm_analysis_calls", "llm_analysis_calls", "paused_cost_limit", 1.0)
    reason = reason or check_limit("max_unknown_predictions_total", "unknown_predictions_total", "stopped_quality_limit", 1.0)
    reason = reason or check_limit("max_known_negative_hits_total", "known_negative_hits_total", "stopped_quality_limit", 1.0)
    max_best_unknown = getattr(args, "max_best_unknown_predictions", None)
    if reason is None and max_best_unknown not in {None, ""} and best:
        if safe_float(best.get("total_unknown_predictions"), 0.0) > float(max_best_unknown):
            messages.append(f"best_total_unknown_predictions {best.get('total_unknown_predictions')} exceeded {max_best_unknown}")
            reason = "stopped_quality_limit"
    max_best_negative = getattr(args, "max_best_known_negative_hits", None)
    if reason is None and max_best_negative not in {None, ""} and best:
        if safe_float(best.get("total_known_negative_hits"), 0.0) > float(max_best_negative):
            messages.append(f"best_total_known_negative_hits {best.get('total_known_negative_hits')} exceeded {max_best_negative}")
            reason = "stopped_quality_limit"
    max_plateau = getattr(args, "max_plateau_iterations", None)
    if reason is None and max_plateau not in {None, ""}:
        if plateau_count >= int(max_plateau):
            messages.append(f"plateau_count {plateau_count} reached {max_plateau}")
            reason = "stopped_plateau"
    return GuardrailResult(triggered=reason is not None, stop_reason=reason, messages=messages, metrics=metrics)


def prune_calibration_artifacts(run_dir: Path, *, mode: str = "analysis-only", dry_run: bool = False, require_summary: bool = True) -> dict[str, Any]:
    mode = str(mode or "off")
    if mode == "off":
        return {"schema_version": "dupe_engine_prune_report_v0_10_7", "mode": mode, "status": "disabled", "run_dir": str(run_dir)}
    keep_suffixes = KEEP_SUFFIXES_BY_MODE.get(mode)
    if keep_suffixes is None:
        raise ValueError(f"Unsupported prune mode: {mode}")
    run_dir = Path(run_dir).resolve()
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory does not exist: {run_dir}")
    required_any = ["scorecard.json", "calibration_loop_state.json", "iteration_summary.json", "run_summary.json"]
    if require_summary and not any((run_dir / name).exists() for name in required_any):
        return {
            "schema_version": "dupe_engine_prune_report_v0_10_7",
            "mode": mode,
            "status": "skipped_missing_summary",
            "run_dir": str(run_dir),
            "required_any": required_any,
        }
    before = dir_size_bytes(run_dir)
    deleted: list[str] = []
    kept: list[str] = []
    for item in sorted(run_dir.rglob("*")):
        if not item.is_file():
            continue
        suffix = item.suffix.lower()
        if suffix in keep_suffixes:
            kept.append(str(item.relative_to(run_dir)))
            continue
        deleted.append(str(item.relative_to(run_dir)))
        if not dry_run:
            try:
                item.unlink()
            except FileNotFoundError:
                pass
    if not dry_run:
        for directory in sorted([p for p in run_dir.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
            try:
                directory.rmdir()
            except OSError:
                pass
    after = dir_size_bytes(run_dir)
    report = {
        "schema_version": "dupe_engine_prune_report_v0_10_7",
        "mode": mode,
        "status": "dry_run" if dry_run else "applied",
        "run_dir": str(run_dir),
        "size_before_bytes": before,
        "size_after_bytes": after if not dry_run else before,
        "bytes_deleted": 0 if dry_run else max(0, before - after),
        "kept_file_count": len(kept),
        "deleted_file_count": len(deleted),
        "kept_files": kept[:500],
        "deleted_files": deleted[:500],
        "truncated_file_lists": len(kept) > 500 or len(deleted) > 500,
    }
    if not dry_run:
        write_json(run_dir / "artifact_prune_report.json", report)
    return report


def write_timing_event(out_dir: Path, **record: Any) -> None:
    payload = {"schema_version": "dupe_engine_timing_event_v0_10_7", "timestamp": now_iso(), **record}
    append_jsonl(out_dir / "timing.jsonl", payload)


def write_error_event(out_dir: Path, **record: Any) -> None:
    payload = {"schema_version": "dupe_engine_error_event_v0_10_7", "timestamp": now_iso(), **record}
    append_jsonl(out_dir / "errors.jsonl", payload)


def write_run_summary(
    out_dir: Path,
    *,
    args: Any,
    iterations: list[dict[str, Any]],
    accepted: dict[str, Any],
    all_rows: list[dict[str, Any]],
    stop_reason: str | None,
    guardrail: GuardrailResult | None,
    started_at: str,
    started_monotonic: float,
    target_metric: str,
    expected_corpus_count: int,
    llm_analysis_calls: int,
) -> dict[str, Any]:
    best = best_group(all_rows, target_metric=target_metric, expected_corpus_count=expected_corpus_count)
    metrics = collect_usage_metrics(all_rows, out_dir=out_dir, llm_analysis_calls=llm_analysis_calls)
    metrics["total_runtime_seconds"] = round(time.time() - started_monotonic, 2)
    summary = {
        "schema_version": "dupe_engine_server_run_summary_v0_10_7",
        "started_at": started_at,
        "updated_at": now_iso(),
        "status": accepted_status(accepted=accepted, stop_reason=stop_reason),
        "stop_reason": stop_reason,
        "target_metric": target_metric,
        "target_recall": safe_float(getattr(args, "target_recall", 0.8), 0.8),
        "iteration_count": len(iterations),
        "row_count": len(all_rows),
        "max_parallel_runs": safe_int(getattr(args, "max_parallel_runs", 1), 1),
        "prune_artifacts": getattr(args, "prune_artifacts", "off"),
        "accepted": accepted,
        "best_candidate": best,
        "usage": metrics,
        "guardrail": {
            "triggered": guardrail.triggered,
            "stop_reason": guardrail.stop_reason,
            "messages": guardrail.messages,
            "metrics": guardrail.metrics,
        } if guardrail else None,
        "artifacts": {
            "decision_log": str(out_dir / "decision_log.jsonl"),
            "timing_log": str(out_dir / "timing.jsonl"),
            "error_log": str(out_dir / "errors.jsonl"),
            "loop_state": str(out_dir / "calibration_loop_state.json"),
        },
    }
    write_json(out_dir / "run_summary.json", summary)
    write_run_summary_md(out_dir / "run_summary.md", summary)
    return summary


def accepted_status(*, accepted: dict[str, Any], stop_reason: str | None) -> str:
    if accepted.get("accepted"):
        return "accepted"
    if stop_reason:
        return stop_reason
    return "running_or_exhausted"


def write_run_summary_md(path: Path, summary: dict[str, Any]) -> None:
    best = summary.get("best_candidate") or {}
    usage = summary.get("usage") or {}
    lines = [
        "# Continuous calibration run summary",
        "",
        f"- Status: `{summary.get('status')}`",
        f"- Stop reason: `{summary.get('stop_reason')}`",
        f"- Target: `{summary.get('target_metric')} >= {summary.get('target_recall')}`",
        f"- Iterations: `{summary.get('iteration_count')}`",
        f"- Rows: `{summary.get('row_count')}`",
        f"- Max parallel runs: `{summary.get('max_parallel_runs')}`",
        "",
        "## Best candidate",
        "",
        f"- Variant: `{best.get('variant_id')}`",
        f"- Worst metric: `{best.get('worst_metric')}`",
        f"- Avg metric: `{best.get('avg_metric')}`",
        f"- Best metric: `{best.get('best_metric')}`",
        f"- Total unknown predictions: `{best.get('total_unknown_predictions')}`",
        f"- Total known negative hits: `{best.get('total_known_negative_hits')}`",
        "",
        "## Usage / guardrails",
        "",
        f"- Runtime seconds: `{usage.get('total_runtime_seconds')}`",
        f"- Output size GB: `{usage.get('run_dir_gb')}`",
        f"- Free disk GB: `{usage.get('free_disk_gb')}`",
        f"- OpenAI OCR attempted: `{usage.get('openai_ocr_attempted')}`",
        f"- Embedding calls: `{usage.get('embedding_calls')}`",
        f"- LLM analysis calls: `{usage.get('llm_analysis_calls')}`",
        "",
        "## Artifacts",
        "",
        f"- Decision log: `{summary.get('artifacts', {}).get('decision_log')}`",
        f"- Timing log: `{summary.get('artifacts', {}).get('timing_log')}`",
        f"- Error log: `{summary.get('artifacts', {}).get('error_log')}`",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_best_config(out_dir: Path, *, rows: list[dict[str, Any]], target_metric: str, expected_corpus_count: int) -> dict[str, Any] | None:
    best = best_group(rows, target_metric=target_metric, expected_corpus_count=expected_corpus_count)
    if not best:
        return None
    write_json(out_dir / "best_config.json", best)
    row = best.get("best_row") or {}
    lines = [
        "# Best calibration config",
        "",
        f"- Variant: `{best.get('variant_id')}`",
        f"- Target metric: `{best.get('target_metric')}`",
        f"- Worst metric: `{best.get('worst_metric')}`",
        f"- Average metric: `{best.get('avg_metric')}`",
        f"- Best metric: `{best.get('best_metric')}`",
        f"- Corpora: `{', '.join(best.get('corpora') or [])}`",
        f"- Total unknown predictions: `{best.get('total_unknown_predictions')}`",
        f"- Total known negative hits: `{best.get('total_known_negative_hits')}`",
        "",
        "## Key knobs",
        "",
        f"- OCR cap: `{row.get('ocr_cap')}`",
        f"- OCR selection mode: `{row.get('ocr_selection_mode')}`",
        f"- Embedding profile: `{row.get('embedding_profile')}`",
        f"- Embedding top-k: `{row.get('embedding_top_k')}`",
        f"- Queue profile: `{row.get('queue_profile')}`",
        f"- Cross-view candidates: `{row.get('cross_view_text_candidates_enabled')}`",
        f"- Rare-token candidates: `{row.get('rare_token_candidates_enabled')}`",
        f"- Candidate cap/job: `{row.get('max_candidates_per_job')}`",
        f"- Candidate cap/page: `{row.get('max_candidates_per_page')}`",
    ]
    (out_dir / "best_config.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return best
