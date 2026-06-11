from __future__ import annotations

import csv
import json
import os
import shutil
from copy import copy
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .calibration_analysis import LlmAnalysisOptions, run_calibration_llm_analysis
from .calibration_observability import (
    append_jsonl,
    build_decision_record,
    evaluate_guardrails,
    prune_calibration_artifacts,
    write_best_config,
    write_error_event,
    write_run_summary,
    write_timing_event,
)
from .calibration_harness import (
    DEFAULT_REASON_QUOTAS,
    VECTOR_PROFILES,
    CalibrationError,
    CalibrationRunSpec,
    build_calibration_corpora,
    build_eval_command,
    build_failed_scorecard_row,
    build_recommendations,
    build_scorecard_row,
    now_iso,
    read_json,
    read_text_tail,
    render_completed_run,
    render_parallel_progress_dashboard,
    run_subprocess_with_progress,
    slug,
    write_json,
    write_run_status,
    write_scorecard,
)

SCHEMA_VERSION = "dupe_engine_calibration_loop_v0_10_7"
DEFAULT_TARGET_RECALL = 0.80
DEFAULT_BATCH_SIZE = 4
DEFAULT_MAX_ITERATIONS = 4
DEFAULT_PARALLEL_HARD_CAP = 10
SUPPORTED_TARGET_METRICS = {
    "strict_recall",
    "any_queue_recall",
    "main_or_secondary_recall",
    "ocr_dependent_recall",
}


class CalibrationLoopError(CalibrationError):
    pass


def run_calibration_loop(args: Any) -> dict[str, Any]:
    pdf_dir = Path(args.pdf_dir).resolve()
    truth = Path(args.truth).resolve()
    out_dir = Path(args.out_dir).resolve()
    started_at = now_iso()
    started_monotonic = time.time()
    if not pdf_dir.exists():
        raise CalibrationLoopError(f"PDF directory does not exist: {pdf_dir}")
    if not truth.exists():
        raise CalibrationLoopError(f"Truth file does not exist: {truth}")
    if not getattr(args, "dry_run", False) and not getattr(args, "confirm_live_ai", False):
        raise CalibrationLoopError("Refusing to execute looped calibration with live AI routes unless --confirm-live-ai is provided. Use --dry-run to write only the first batch plan.")

    target_metric = str(getattr(args, "target_metric", "strict_recall") or "strict_recall")
    if target_metric not in SUPPORTED_TARGET_METRICS:
        raise CalibrationLoopError(f"Unsupported --target-metric: {target_metric}")

    target_recall = float(getattr(args, "target_recall", DEFAULT_TARGET_RECALL) or DEFAULT_TARGET_RECALL)
    max_iterations = int(getattr(args, "max_iterations", DEFAULT_MAX_ITERATIONS) or DEFAULT_MAX_ITERATIONS)
    batch_size = int(getattr(args, "batch_size", DEFAULT_BATCH_SIZE) or DEFAULT_BATCH_SIZE)
    batch_size = max(1, batch_size)

    corpora = build_calibration_corpora(args, pdf_dir, truth)
    out_dir.mkdir(parents=True, exist_ok=True)
    write_timing_event(
        out_dir,
        event="loop_started",
        started_at=started_at,
        target_metric=target_metric,
        target_recall=target_recall,
        max_iterations=max_iterations,
        batch_size=batch_size,
        max_parallel_runs=normalized_max_parallel_runs(args),
        prune_artifacts=getattr(args, "prune_artifacts", "off"),
    )

    seen_signatures: set[tuple[Any, ...]] = set()
    loop_iterations: list[dict[str, Any]] = []
    all_rows: list[dict[str, Any]] = []
    bootstrap_rows = read_bootstrap_rows(getattr(args, "bootstrap_calibration_dir", None))
    if bootstrap_rows:
        all_rows.extend(bootstrap_rows)
    write_root_scorecards(out_dir, all_rows)

    llm_analysis_calls = 0
    stop_reason: str | None = None
    last_best_metric: float | None = None
    plateau_count = 0
    ranked_bootstrap = rank_variant_groups(all_rows, target_metric=target_metric, expected_corpus_count=len(corpora))
    if ranked_bootstrap:
        last_best_metric = floatish(ranked_bootstrap[0].get("worst_metric"), 0.0)

    accepted = evaluate_acceptance(
        all_rows,
        target_metric=target_metric,
        target_recall=target_recall,
        expected_corpus_count=len(corpora),
        max_known_negative_hits=getattr(args, "accept_max_known_negative_hits", None),
        max_unknown_predictions=getattr(args, "accept_max_unknown_predictions", None),
        max_candidates_per_100_pages=getattr(args, "accept_max_candidates_per_100_pages", None),
    )

    if accepted["accepted"]:
        stop_reason = "accepted"
        write_loop_state(out_dir, args, corpora, loop_iterations, accepted, bootstrap_rows=bootstrap_rows)
        write_best_config(out_dir, rows=all_rows, target_metric=target_metric, expected_corpus_count=len(corpora))
        write_run_summary(out_dir, args=args, iterations=loop_iterations, accepted=accepted, all_rows=all_rows, stop_reason=stop_reason, guardrail=None, started_at=started_at, started_monotonic=started_monotonic, target_metric=target_metric, expected_corpus_count=len(corpora), llm_analysis_calls=llm_analysis_calls)
        return build_loop_result(out_dir, planned_run_count=0, executed_run_count=0, accepted=accepted, iterations=loop_iterations, dry_run=bool(getattr(args, "dry_run", False)), stop_reason=stop_reason)

    aggressive_search = bool(getattr(args, "aggressive_search", False))
    current_variants = build_seed_variants(batch_size=batch_size, aggressive=aggressive_search)
    if bootstrap_rows:
        current_variants = plan_next_variants(bootstrap_rows, iteration=1, batch_size=batch_size, seen_signatures=seen_signatures, aggressive=aggressive_search)
    current_specs = variants_to_specs(current_variants, corpora, iteration=1, profile_name="loop_recall", seen_signatures=seen_signatures)

    write_loop_state(out_dir, args, corpora, loop_iterations, accepted, bootstrap_rows=bootstrap_rows, next_specs=current_specs)

    if getattr(args, "dry_run", False):
        iter_dir = out_dir / "iteration_01"
        write_iteration_manifest(iter_dir, args, corpora, current_specs, iteration=1, target_recall=target_recall, target_metric=target_metric, dry_run=True)
        write_scorecard(iter_dir / "scorecard.csv", [])
        write_json(iter_dir / "scorecard.json", {"schema_version": "dupe_engine_calibration_loop_scorecard_v0_10_7", "rows": []})
        append_jsonl(
            out_dir / "decision_log.jsonl",
            {
                "schema_version": "dupe_engine_decision_log_v0_10_7",
                "event": "dry_run_plan",
                "timestamp": now_iso(),
                "planned_run_count": len(current_specs),
                "next_variant_ids": [str(variant.get("variant_id")) for variant in current_variants],
            },
        )
        write_run_summary(out_dir, args=args, iterations=loop_iterations, accepted=accepted, all_rows=all_rows, stop_reason="dry_run_plan", guardrail=None, started_at=started_at, started_monotonic=started_monotonic, target_metric=target_metric, expected_corpus_count=len(corpora), llm_analysis_calls=llm_analysis_calls)
        return build_loop_result(out_dir, planned_run_count=len(current_specs), executed_run_count=0, accepted=accepted, iterations=loop_iterations, dry_run=True, stop_reason="dry_run_plan")

    executed_total = 0
    planned_total = 0
    last_guardrail = None
    for iteration in range(1, max_iterations + 1):
        if not current_specs:
            stop_reason = "stopped_no_planned_runs"
            break
        iter_dir = out_dir / f"iteration_{iteration:02d}"
        planned_total += len(current_specs)
        iter_started = time.time()
        write_timing_event(out_dir, event="iteration_started", iteration=iteration, planned_run_count=len(current_specs), iter_dir=str(iter_dir))
        try:
            rows = execute_iteration(args, iter_dir, current_specs, corpora, iteration, target_recall, target_metric)
        except Exception as exc:
            write_error_event(out_dir, event="iteration_failed", iteration=iteration, error_message=str(exc), error_type=type(exc).__name__)
            raise
        iteration_elapsed_seconds = time.time() - iter_started
        write_timing_event(out_dir, event="iteration_runs_completed", iteration=iteration, elapsed_seconds=round(iteration_elapsed_seconds, 2), row_count=len(rows))
        executed_total += len([row for row in rows if not truthy(row.get("reused"))])
        all_rows.extend(rows)
        write_root_scorecards(out_dir, all_rows)

        analysis_result = run_iteration_analysis(args, iter_dir)
        if isinstance(analysis_result, dict) and analysis_result.get("status") != "disabled":
            llm_analysis_calls += 1
        accepted = evaluate_acceptance(
            all_rows,
            target_metric=target_metric,
            target_recall=target_recall,
            expected_corpus_count=len(corpora),
            max_known_negative_hits=getattr(args, "accept_max_known_negative_hits", None),
            max_unknown_predictions=getattr(args, "accept_max_unknown_predictions", None),
            max_candidates_per_100_pages=getattr(args, "accept_max_candidates_per_100_pages", None),
        )

        ranked = rank_variant_groups(all_rows, target_metric=target_metric, expected_corpus_count=len(corpora))
        current_best_metric = floatish(ranked[0].get("worst_metric"), 0.0) if ranked else 0.0
        previous_best_metric = last_best_metric
        min_gain = floatish(getattr(args, "min_recall_gain", 0.01), 0.01)
        if previous_best_metric is None or current_best_metric >= previous_best_metric + min_gain:
            plateau_count = 0
            last_best_metric = current_best_metric
        else:
            plateau_count += 1
            if previous_best_metric is not None and current_best_metric > previous_best_metric:
                last_best_metric = current_best_metric

        guardrail = evaluate_guardrails(
            args,
            out_dir=out_dir,
            all_rows=all_rows,
            started_monotonic=started_monotonic,
            iteration_elapsed_seconds=iteration_elapsed_seconds,
            plateau_count=plateau_count,
            llm_analysis_calls=llm_analysis_calls,
            target_metric=target_metric,
            expected_corpus_count=len(corpora),
        )
        last_guardrail = guardrail
        if accepted["accepted"]:
            stop_reason = "accepted"
        elif guardrail.triggered:
            stop_reason = guardrail.stop_reason

        next_variants: list[dict[str, Any]] = []
        next_specs: list[CalibrationRunSpec] = []
        if not stop_reason:
            next_variants = plan_next_variants(all_rows, iteration=iteration + 1, batch_size=batch_size, seen_signatures=seen_signatures, aggressive=aggressive_search)
            next_specs = variants_to_specs(next_variants, corpora, iteration=iteration + 1, profile_name="loop_recall", seen_signatures=seen_signatures)

        iteration_summary = {
            "schema_version": "dupe_engine_iteration_summary_v0_10_7",
            "iteration": iteration,
            "iteration_dir": str(iter_dir),
            "planned_run_count": len(current_specs),
            "executed_or_reused_run_count": len(rows),
            "elapsed_seconds": round(iteration_elapsed_seconds, 2),
            "accepted": accepted,
            "analysis": analysis_result,
            "best_configs": rank_variant_groups(all_rows, target_metric=target_metric, expected_corpus_count=len(corpora))[:5],
            "plateau_count": plateau_count,
            "guardrail": {
                "triggered": guardrail.triggered,
                "stop_reason": guardrail.stop_reason,
                "messages": guardrail.messages,
                "metrics": guardrail.metrics,
            },
            "stop_reason": stop_reason,
        }
        write_json(iter_dir / "iteration_summary.json", iteration_summary)
        loop_iterations.append(iteration_summary)

        decision_record = build_decision_record(
            iteration=iteration,
            rows=all_rows,
            iteration_rows=rows,
            target_metric=target_metric,
            target_recall=target_recall,
            expected_corpus_count=len(corpora),
            previous_best=previous_best_metric,
            plateau_count=plateau_count,
            accepted=accepted,
            analysis=analysis_result,
            next_variants=next_variants,
            stop_reason=stop_reason,
            guardrails={
                "triggered": guardrail.triggered,
                "stop_reason": guardrail.stop_reason,
                "messages": guardrail.messages,
                "metrics": guardrail.metrics,
            },
            iteration_elapsed_seconds=iteration_elapsed_seconds,
        )
        append_jsonl(out_dir / "decision_log.jsonl", decision_record)

        if next_specs:
            write_json(
                iter_dir / "next_batch_plan.json",
                {
                    "schema_version": "dupe_engine_next_calibration_batch_v0_10_7",
                    "iteration": iteration,
                    "next_iteration": iteration + 1,
                    "target_metric": target_metric,
                    "target_recall": target_recall,
                    "planner": "deterministic_metrics_planner_with_llm_analysis_log_and_guardrails",
                    "analysis_md": analysis_result.get("analysis_md") if isinstance(analysis_result, dict) else None,
                    "variants": next_variants,
                    "runs": [asdict(spec) for spec in next_specs],
                },
            )

        write_best_config(out_dir, rows=all_rows, target_metric=target_metric, expected_corpus_count=len(corpora))
        write_loop_state(out_dir, args, corpora, loop_iterations, accepted, bootstrap_rows=bootstrap_rows, next_specs=next_specs)
        write_run_summary(out_dir, args=args, iterations=loop_iterations, accepted=accepted, all_rows=all_rows, stop_reason=stop_reason, guardrail=guardrail, started_at=started_at, started_monotonic=started_monotonic, target_metric=target_metric, expected_corpus_count=len(corpora), llm_analysis_calls=llm_analysis_calls)

        prune_mode = str(getattr(args, "prune_artifacts", "off") or "off")
        if prune_mode != "off":
            prune_report = prune_calibration_artifacts(iter_dir, mode=prune_mode, dry_run=bool(getattr(args, "prune_dry_run", False)), require_summary=True)
            write_timing_event(out_dir, event="iteration_pruned", iteration=iteration, mode=prune_mode, status=prune_report.get("status"), bytes_deleted=prune_report.get("bytes_deleted"))

        if stop_reason:
            break
        current_specs = next_specs

    if not stop_reason and not accepted.get("accepted"):
        stop_reason = "stopped_max_iterations"
    write_root_scorecards(out_dir, all_rows)
    write_best_config(out_dir, rows=all_rows, target_metric=target_metric, expected_corpus_count=len(corpora))
    write_loop_state(out_dir, args, corpora, loop_iterations, accepted, bootstrap_rows=bootstrap_rows, next_specs=[])
    write_run_summary(out_dir, args=args, iterations=loop_iterations, accepted=accepted, all_rows=all_rows, stop_reason=stop_reason, guardrail=last_guardrail, started_at=started_at, started_monotonic=started_monotonic, target_metric=target_metric, expected_corpus_count=len(corpora), llm_analysis_calls=llm_analysis_calls)
    write_timing_event(out_dir, event="loop_finished", stop_reason=stop_reason, planned_run_count=planned_total, executed_run_count=executed_total)
    return build_loop_result(out_dir, planned_run_count=planned_total, executed_run_count=executed_total, accepted=accepted, iterations=loop_iterations, dry_run=False, stop_reason=stop_reason)


def write_root_scorecards(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    write_scorecard(out_dir / "scorecard.csv", rows)
    write_json(out_dir / "scorecard.json", {"schema_version": "dupe_engine_calibration_loop_scorecard_v0_10_7", "rows": rows})

def execute_iteration(
    args: Any,
    iter_dir: Path,
    specs: list[CalibrationRunSpec],
    corpora: list[dict[str, str]],
    iteration: int,
    target_recall: float,
    target_metric: str,
) -> list[dict[str, Any]]:
    iter_dir.mkdir(parents=True, exist_ok=True)
    write_iteration_manifest(iter_dir, args, corpora, specs, iteration=iteration, target_recall=target_recall, target_metric=target_metric, dry_run=False)
    rows: list[dict[str, Any]] = []
    root = Path(__file__).resolve().parents[2]
    src = str(root / "src")
    total_runs = len(specs)
    max_parallel = normalized_max_parallel_runs(args)
    progress_mode = str(getattr(args, "progress", "tui") or "tui")
    aggregate_tui = max_parallel > 1 and progress_mode == "tui"
    child_progress_mode = "none" if aggregate_tui else progress_mode

    def run_one(index: int, spec: CalibrationRunSpec) -> dict[str, Any]:
        run_dir = iter_dir / "runs" / spec.run_id
        run_config_path = run_dir / "run_config.json"
        status = read_json(run_dir / "run_status.json")
        existing_complete = (run_dir / "truth_eval.json").exists() and (run_dir / "phase_eval.json").exists()
        if status.get("status") == "running" and (getattr(args, "resume", False) or getattr(args, "skip_existing", False)):
            status.update({"status": "aborted", "completed_at": now_iso(), "error_message": "Previous calibration process exited before marking this run complete."})
            write_json(run_dir / "run_status.json", status)
        if existing_complete and (getattr(args, "skip_existing", False) or getattr(args, "resume", False)):
            return build_scorecard_row(spec, run_dir, reused=True)
        if status.get("status") in {"failed", "aborted"} and (getattr(args, "resume", False) or getattr(args, "skip_existing", False)) and not getattr(args, "retry_failed", False):
            return build_failed_scorecard_row(spec, run_dir, status=status, reused=True)
        if run_dir.exists() and not getattr(args, "resume", False) and not getattr(args, "skip_existing", False):
            shutil.rmtree(run_dir)
        run_dir.mkdir(parents=True, exist_ok=True)
        write_json(run_config_path, asdict(spec))
        started = time.time()
        spec_pdf_dir = Path(spec.pdf_dir).resolve()
        spec_truth = Path(spec.truth).resolve()
        cmd = build_eval_command(spec, spec_pdf_dir, spec_truth, run_dir, args)
        env = os.environ.copy()
        env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        (run_dir / "command.txt").write_text(" ".join(cmd) + "\n", encoding="utf-8")
        write_run_status(run_dir, spec, status="running", command=cmd, started_at=now_iso())
        returncode = run_subprocess_with_progress(
            cmd,
            cwd=root,
            env=env,
            run_dir=run_dir,
            spec=spec,
            run_index=index,
            total_runs=total_runs,
            progress_mode=child_progress_mode,
        )
        if returncode != 0:
            error = {
                "status": "failed",
                "returncode": returncode,
                "completed_at": now_iso(),
                "error_message": f"Sub-run failed with exit code {returncode}",
                "stdout_tail": read_text_tail(run_dir / "stdout.log"),
            }
            write_json(run_dir / "run_error.json", error)
            write_run_status(run_dir, spec, status="failed", exit_code=returncode, completed_at=now_iso(), error_message=error["error_message"])
            return build_failed_scorecard_row(spec, run_dir, status=error, runtime_seconds=round(time.time() - started, 2), reused=False)
        write_run_status(run_dir, spec, status="succeeded", exit_code=0, completed_at=now_iso())
        return build_scorecard_row(spec, run_dir, runtime_seconds=round(time.time() - started, 2), reused=False)

    def record_row(row: dict[str, Any]) -> None:
        rows.append(row)
        write_scorecard(iter_dir / "scorecard.csv", rows)
        write_json(iter_dir / "scorecard.json", {"schema_version": "dupe_engine_calibration_loop_scorecard_v0_10_7", "rows": rows})
        completion_mode = "none" if aggregate_tui else getattr(args, "progress", "tui")
        if row.get("status") == "succeeded" and not truthy(row.get("reused")):
            render_completed_run(row, mode=completion_mode)

    if max_parallel <= 1 or len(specs) <= 1:
        for index, spec in enumerate(specs, start=1):
            row = run_one(index, spec)
            record_row(row)
            if row.get("status") not in {None, "succeeded"} and getattr(args, "fail_fast", False):
                raise CalibrationLoopError(f"Sub-run {spec.run_id} failed. See {iter_dir / 'runs' / spec.run_id / 'stdout.log'}")
    else:
        started = time.time()
        last_render = 0.0
        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            future_map = {executor.submit(run_one, index, spec): (index, spec) for index, spec in enumerate(specs, start=1)}
            pending = set(future_map)
            while pending:
                done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
                now = time.time()
                if aggregate_tui and now - last_render >= 1.0:
                    render_parallel_progress_dashboard(
                        iter_dir,
                        specs,
                        iteration=iteration,
                        target_recall=target_recall,
                        target_metric=target_metric,
                        started=started,
                        max_parallel=max_parallel,
                    )
                    last_render = now
                for future in done:
                    _index, spec = future_map[future]
                    try:
                        row = future.result()
                    except Exception as exc:
                        run_dir = iter_dir / "runs" / spec.run_id
                        run_dir.mkdir(parents=True, exist_ok=True)
                        status = {"status": "failed", "error_message": str(exc), "completed_at": now_iso()}
                        write_json(run_dir / "run_error.json", status)
                        write_run_status(run_dir, spec, status="failed", completed_at=now_iso(), error_message=str(exc))
                        row = build_failed_scorecard_row(spec, run_dir, status=status, reused=False)
                    record_row(row)
                    if row.get("status") not in {None, "succeeded"} and getattr(args, "fail_fast", False):
                        for future_to_cancel in pending:
                            future_to_cancel.cancel()
                        raise CalibrationLoopError(f"Sub-run {spec.run_id} failed. See {iter_dir / 'runs' / spec.run_id / 'stdout.log'}")
            if aggregate_tui:
                render_parallel_progress_dashboard(
                    iter_dir,
                    specs,
                    iteration=iteration,
                    target_recall=target_recall,
                    target_metric=target_metric,
                    started=started,
                    max_parallel=max_parallel,
                    final=True,
                )

    rows.sort(key=lambda row: str(row.get("run_id") or ""))
    recommendations = build_recommendations(rows)
    write_json(iter_dir / "recommended_configs.json", recommendations)
    write_scorecard(iter_dir / "scorecard.csv", rows)
    write_json(iter_dir / "scorecard.json", {"schema_version": "dupe_engine_calibration_loop_scorecard_v0_10_7", "rows": rows, "recommendations": recommendations})
    return rows


def normalized_max_parallel_runs(args: Any) -> int:
    try:
        requested = int(getattr(args, "max_parallel_runs", 1) or 1)
    except Exception:
        requested = 1
    try:
        hard_cap = int(getattr(args, "parallel_hard_cap", DEFAULT_PARALLEL_HARD_CAP) or DEFAULT_PARALLEL_HARD_CAP)
    except Exception:
        hard_cap = DEFAULT_PARALLEL_HARD_CAP
    hard_cap = max(1, hard_cap)
    return max(1, min(requested, hard_cap))


def parse_parallel_candidates(value: Any) -> list[int]:
    raw = str(value or "10,6")
    parsed: list[int] = []
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        try:
            count = int(token)
        except ValueError as exc:
            raise CalibrationLoopError(f"Invalid --parallel-candidates value: {token!r}") from exc
        if count < 1:
            raise CalibrationLoopError("Parallel candidates must be positive integers")
        if count not in parsed:
            parsed.append(count)
    if not parsed:
        raise CalibrationLoopError("At least one --parallel-candidates value is required")
    return parsed


def run_calibration_loop_stress(args: Any) -> dict[str, Any]:
    """Try high-parallel loop runs and fall back if a trial produces failures.

    The stress command answers a workstation capacity question. A trial is
    considered capacity-successful when the loop command itself completes and
    no sub-run scorecard rows are marked failed/aborted. It does not require
    hitting the recall target, because this wrapper is about throughput first.
    """

    root_out = Path(args.out_dir).resolve()
    root_out.mkdir(parents=True, exist_ok=True)
    candidates = parse_parallel_candidates(getattr(args, "parallel_candidates", "10,6"))
    trials: list[dict[str, Any]] = []
    selected_parallel: int | None = None

    for requested_parallel in candidates:
        trial_args = copy(args)
        trial_parallel = max(1, min(int(requested_parallel), int(getattr(args, "parallel_hard_cap", DEFAULT_PARALLEL_HARD_CAP) or DEFAULT_PARALLEL_HARD_CAP)))
        trial_out = root_out / f"p{trial_parallel}"
        setattr(trial_args, "max_parallel_runs", trial_parallel)
        setattr(trial_args, "out_dir", str(trial_out))
        status = "succeeded"
        error_message = None
        result: dict[str, Any] = {}
        try:
            result = run_calibration_loop(trial_args)
        except Exception as exc:  # preserve the stress summary before raising/falling back
            status = "failed"
            error_message = str(exc)
        rows = collect_loop_scorecard_rows(trial_out)
        failed_rows = [row for row in rows if row.get("status") not in {None, "succeeded"}]
        trial_summary = {
            "max_parallel_runs": trial_parallel,
            "requested_parallel_runs": requested_parallel,
            "out_dir": str(trial_out),
            "status": "failed" if failed_rows and status == "succeeded" else status,
            "error_message": error_message,
            "failed_run_count": len(failed_rows),
            "scorecard_row_count": len(rows),
            "result": result,
        }
        trials.append(trial_summary)
        if trial_summary["status"] == "succeeded" and not failed_rows:
            selected_parallel = trial_parallel
            if not bool(getattr(args, "stress_continue_after_success", False)):
                break

    summary = {
        "schema_version": "dupe_engine_parallel_stress_v0_10_7",
        "selected_parallel_runs": selected_parallel,
        "parallel_candidates": candidates,
        "trials": trials,
    }
    write_json(root_out / "parallel_stress_summary.json", summary)
    return {
        "out_dir": str(root_out),
        "selected_parallel_runs": selected_parallel,
        "summary_json": str(root_out / "parallel_stress_summary.json"),
        "trials": trials,
    }


def collect_loop_scorecard_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    rows.extend(read_scorecard_rows_from_dir(path))
    for scorecard_dir in sorted(path.glob("iteration_*")):
        rows.extend(read_scorecard_rows_from_dir(scorecard_dir))
    return rows


def write_iteration_manifest(
    iter_dir: Path,
    args: Any,
    corpora: list[dict[str, str]],
    specs: list[CalibrationRunSpec],
    *,
    iteration: int,
    target_recall: float,
    target_metric: str,
    dry_run: bool,
) -> None:
    write_json(
        iter_dir / "calibration_manifest.json",
        {
            "schema_version": "dupe_engine_calibration_loop_iteration_v0_10_7",
            "iteration": iteration,
            "profile": "loop_recall",
            "target_recall": target_recall,
            "target_metric": target_metric,
            "planned_run_count": len(specs),
            "aggressive_search": bool(getattr(args, "aggressive_search", False)),
            "corpora": corpora,
            "runs": [asdict(spec) for spec in specs],
            "safety": {
                "confirm_live_ai": bool(getattr(args, "confirm_live_ai", False)),
                "dry_run": bool(dry_run),
                "max_parallel_runs": normalized_max_parallel_runs(args),
                "parallel_hard_cap": int(getattr(args, "parallel_hard_cap", DEFAULT_PARALLEL_HARD_CAP) or DEFAULT_PARALLEL_HARD_CAP),
                "llm_analysis_live": not bool(getattr(args, "no_llm_analysis", False)) and not bool(getattr(args, "llm_analysis_dry_run", False)),
                "llm_analysis_nonfatal": not bool(getattr(args, "fatal_llm_analysis", False)),
            },
            "planner_note": "Looped calibration can compare candidate-generation knobs and acceptance thresholds; v0.10.7 supports high-parallel stress runs up to the configured hard cap and keeps a compact aggregate TUI for larger batches.",
        },
    )


def run_iteration_analysis(args: Any, iter_dir: Path) -> dict[str, Any]:
    if bool(getattr(args, "no_llm_analysis", False)):
        return {"status": "disabled"}
    try:
        return run_calibration_llm_analysis(
            iter_dir,
            LlmAnalysisOptions(
                enabled=True,
                dry_run=bool(getattr(args, "llm_analysis_dry_run", False)),
                include_text_snippets=bool(getattr(args, "llm_analysis_include_text_snippets", False)),
                model=getattr(args, "llm_analysis_model", None),
                output_md=getattr(args, "llm_analysis_out", None),
                output_json=getattr(args, "llm_analysis_json_out", None),
            ),
        )
    except Exception as exc:
        if bool(getattr(args, "fatal_llm_analysis", False)):
            raise
        analysis_json = iter_dir / "llm_analysis.json"
        analysis_md = iter_dir / "llm_analysis.md"
        result = {
            "schema_version": "dupe_engine_calibration_llm_analysis_v0_10_7",
            "calibration_dir": str(iter_dir),
            "status": "failed_nonfatal",
            "provider": "llm_or_analysis",
            "model": getattr(args, "llm_analysis_model", None),
            "metrics_only": not bool(getattr(args, "llm_analysis_include_text_snippets", False)),
            "error_message": str(exc),
            "analysis_json": str(analysis_json),
            "analysis_md": str(analysis_md),
        }
        write_json(analysis_json, result)
        analysis_md.write_text(
            "# Calibration LLM analysis failed non-fatally\n\n"
            "The calibration sub-runs completed, but the optional LLM analysis step failed. "
            "The loop continued because analysis is observational in this harness.\n\n"
            f"Error: `{exc}`\n",
            encoding="utf-8",
        )
        return result


def build_seed_variants(*, batch_size: int, aggressive: bool = False) -> list[dict[str, Any]]:
    variants = [
        {
            "variant_id": "seed_v0102_champion_control",
            "planner_reason": "Rerun the v0.10.2-style champion control with new v0.10.3 candidate generators disabled.",
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "ocr_reason_quotas": DEFAULT_REASON_QUOTAS,
            "vector_profile": "balanced",
            "queue_profile": "recall_first",
            "ocr_evidence_upgrade_enabled": True,
            "openai_ocr_max_pages_per_document": 8,
            "cross_view_text_candidates_enabled": False,
            "rare_token_candidates_enabled": False,
        },
        {
            "variant_id": "seed_cross_view_candidate_recall",
            "planner_reason": "Test cross-source OCR/native TF-IDF candidate generation while keeping candidate caps bounded.",
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "ocr_reason_quotas": DEFAULT_REASON_QUOTAS,
            "vector_profile": "balanced",
            "queue_profile": "recall_first",
            "ocr_evidence_upgrade_enabled": True,
            "openai_ocr_max_pages_per_document": 8,
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "loose_tfidf_threshold": 0.70,
            "multipass_text_top_k": 8,
            "max_candidates_per_job": 3500,
            "max_candidates_per_page": 70,
        },
        {
            "variant_id": "seed_rare_token_candidate_recall",
            "planner_reason": "Test bounded rare-token/source-token blocking for OCR-ready but not-candidate-generated misses.",
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "ocr_reason_quotas": DEFAULT_REASON_QUOTAS,
            "vector_profile": "balanced",
            "queue_profile": "recall_first",
            "ocr_evidence_upgrade_enabled": True,
            "openai_ocr_max_pages_per_document": 8,
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "rare_token_min_overlap": 2,
            "rare_token_min_jaccard": 0.14,
            "rare_token_max_df": 10,
            "max_candidates_per_job": 3500,
            "max_candidates_per_page": 70,
        },
        {
            "variant_id": "seed_sequence_crossview_wide",
            "planner_reason": "Combine cross-view text with a wider but bounded sequence-neighbor window for group/sequence misses.",
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "ocr_reason_quotas": DEFAULT_REASON_QUOTAS,
            "vector_profile": "balanced",
            "queue_profile": "recall_first",
            "ocr_evidence_upgrade_enabled": True,
            "openai_ocr_max_pages_per_document": 8,
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "loose_tfidf_threshold": 0.70,
            "multipass_text_top_k": 8,
            "sequence_anchor_min_confidence": 0.82,
            "sequence_neighbor_window": 2,
            "sequence_min_text_similarity": 0.30,
            "sequence_min_text_similarity_with_visual": 0.16,
            "sequence_visual_support_phash_threshold": 32,
            "rare_token_min_overlap": 2,
            "rare_token_min_jaccard": 0.14,
            "rare_token_max_df": 10,
            "max_candidates_per_job": 4000,
            "max_candidates_per_page": 80,
        },
        {
            "variant_id": "seed_vector_candidate_support",
            "planner_reason": "Test candidate-generation improvements plus wider vector support without adjudication.",
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "ocr_reason_quotas": DEFAULT_REASON_QUOTAS,
            "vector_profile": "recall_first",
            "embedding_top_k": 12,
            "embedding_min_similarity": 0.80,
            "embedding_min_margin": 0.01,
            "embedding_max_candidates_per_page": 3,
            "embedding_max_candidates_per_job": 700,
            "queue_profile": "recall_first",
            "ocr_evidence_upgrade_enabled": True,
            "openai_ocr_max_pages_per_document": 8,
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
        },
    ]
    if aggressive:
        variants.extend([
            {
                "variant_id": "seed_emergency_wide_recall",
                "planner_reason": "Emergency recall search: loosen deterministic, sequence, rare-token, OCR, vector, and review limits to find recall even if unknown predictions rise.",
                "ocr_cap": 300,
                "ocr_selection_mode": "reason_balanced",
                "ocr_reason_quotas": "vision_expected:25,weak_tesseract:30,no_text:25,candidate_based:20",
                "vector_profile": "recall_first",
                "embedding_top_k": 24,
                "embedding_min_similarity": 0.72,
                "embedding_min_margin": 0.0,
                "embedding_max_candidates_per_page": 5,
                "embedding_max_candidates_per_job": 1800,
                "queue_profile": "recall_first",
                "ocr_evidence_upgrade_enabled": True,
                "openai_ocr_max_pages_per_document": 14,
                "openai_ocr_min_candidate_confidence": 0.35,
                "cross_view_text_candidates_enabled": True,
                "rare_token_candidates_enabled": True,
                "rare_token_min_overlap": 2,
                "rare_token_min_jaccard": 0.08,
                "rare_token_max_df": 18,
                "loose_tfidf_threshold": 0.55,
                "standard_tfidf_threshold": 0.72,
                "multipass_text_top_k": 20,
                "sequence_anchor_min_confidence": 0.70,
                "sequence_neighbor_window": 3,
                "sequence_min_text_similarity": 0.18,
                "sequence_min_text_similarity_with_visual": 0.10,
                "sequence_visual_support_phash_threshold": 40,
                "max_candidates_per_job": 8000,
                "max_candidates_per_page": 160,
                "main_review_min_confidence": 0.62,
                "main_review_max_candidates_per_100_pages": 220,
            },
            {
                "variant_id": "seed_v4_visual_sequence_sweep",
                "planner_reason": "V4-heavy stress variant: push sequence/visual support and source-safe text candidates while keeping OCR and embedding wide.",
                "ocr_cap": 275,
                "ocr_selection_mode": "reason_balanced",
                "ocr_reason_quotas": "vision_expected:30,weak_tesseract:25,no_text:20,candidate_based:25",
                "vector_profile": "recall_first",
                "embedding_top_k": 20,
                "embedding_min_similarity": 0.74,
                "embedding_min_margin": 0.0,
                "embedding_max_candidates_per_page": 5,
                "embedding_max_candidates_per_job": 1600,
                "queue_profile": "recall_first",
                "ocr_evidence_upgrade_enabled": True,
                "openai_ocr_max_pages_per_document": 14,
                "cross_view_text_candidates_enabled": True,
                "rare_token_candidates_enabled": True,
                "rare_token_min_overlap": 2,
                "rare_token_min_jaccard": 0.09,
                "rare_token_max_df": 18,
                "loose_tfidf_threshold": 0.58,
                "standard_tfidf_threshold": 0.74,
                "multipass_text_top_k": 18,
                "sequence_anchor_min_confidence": 0.68,
                "sequence_neighbor_window": 3,
                "sequence_min_text_similarity": 0.16,
                "sequence_min_text_similarity_with_visual": 0.08,
                "sequence_visual_support_phash_threshold": 42,
                "max_candidates_per_job": 7500,
                "max_candidates_per_page": 150,
                "main_review_min_confidence": 0.60,
                "main_review_max_candidates_per_100_pages": 240,
            },
        ])
    return variants[:batch_size]


def plan_next_variants(
    rows: list[dict[str, Any]],
    *,
    iteration: int,
    batch_size: int,
    seen_signatures: set[tuple[Any, ...]],
    aggressive: bool = False,
) -> list[dict[str, Any]]:
    ranked = rank_variant_groups(rows, target_metric="strict_recall", expected_corpus_count=0)
    variants: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    top_groups = ranked[:2] or []
    for group in top_groups:
        base = row_to_variant(group.get("best_row") or {})
        counts = group.get("false_negative_reason_counts") or {}
        candidates.extend(mutate_variant(base, counts, iteration=iteration, aggressive=aggressive))
    if not candidates:
        candidates = build_seed_variants(batch_size=batch_size, aggressive=aggressive)
    if aggressive:
        candidates.sort(key=aggressive_variant_priority)
    used_variant_ids: dict[str, int] = {}
    for variant in candidates:
        variant = uniquify_variant_id(dict(variant), used_variant_ids)
        signature = variant_signature(variant)
        if signature in seen_signatures:
            continue
        variants.append(variant)
        if len(variants) >= batch_size:
            break
    if len(variants) < batch_size:
        for variant in fallback_variants(iteration, aggressive=aggressive):
            variant = uniquify_variant_id(dict(variant), used_variant_ids)
            signature = variant_signature(variant)
            if signature in seen_signatures:
                continue
            variants.append(variant)
            if len(variants) >= batch_size:
                break
    return variants




def uniquify_variant_id(variant: dict[str, Any], used_variant_ids: dict[str, int]) -> dict[str, Any]:
    base_id = str(variant.get("variant_id") or "variant")
    count = used_variant_ids.get(base_id, 0)
    used_variant_ids[base_id] = count + 1
    if count:
        variant["variant_id"] = f"{base_id}_alt{count + 1}"
    return variant


def aggressive_variant_priority(variant: dict[str, Any]) -> tuple[int, str]:
    variant_id = str(variant.get("variant_id") or "")
    if "champion_control" in variant_id or "champion" in variant_id:
        return (0, variant_id)
    if "emergency_wide_recall" in variant_id:
        return (1, variant_id)
    if "v4_visual_sequence" in variant_id:
        return (2, variant_id)
    if "candidate_threshold" in variant_id or "cross_view" in variant_id:
        return (3, variant_id)
    if "ocr_budget" in variant_id:
        return (4, variant_id)
    if "vector" in variant_id:
        return (5, variant_id)
    if "review_acceptance" in variant_id:
        return (6, variant_id)
    return (7, variant_id)


def mutate_variant(base: dict[str, Any], counts: dict[str, int], *, iteration: int, aggressive: bool = False) -> list[dict[str, Any]]:
    mutations: list[dict[str, Any]] = []
    fallback_pressure = int(counts.get("fallback_not_selected", 0)) + int(counts.get("fallback_selected_but_still_weak", 0))
    candidate_pressure = int(counts.get("deterministic_threshold_or_candidate_generation_miss", 0)) + int(counts.get("ocr_or_vision_layer_miss", 0))
    semantic_pressure = int(counts.get("semantic_or_adjudication_layer_miss", 0))

    control = dict(base)
    control.update({
        "variant_id": f"loop{iteration:02d}_champion_control",
        "planner_reason": "Rerun the current champion as a control before trusting new candidate-generation mutations.",
        "cross_view_text_candidates_enabled": bool(base.get("cross_view_text_candidates_enabled", False)),
        "rare_token_candidates_enabled": bool(base.get("rare_token_candidates_enabled", False)),
    })
    mutations.append(control)

    if candidate_pressure or not counts:
        variant = dict(base)
        variant.update({
            "variant_id": f"loop{iteration:02d}_candidate_threshold_relax_generation",
            "planner_reason": "Previous misses point to candidate-generation pressure; enable cross-view text, rare-token blocking, loosen sequence/text thresholds, and expand candidate caps.",
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "rare_token_min_overlap": max(2, intish(base.get("rare_token_min_overlap"), 3) - 1),
            "rare_token_min_jaccard": lower_float(base.get("rare_token_min_jaccard"), default=0.20, step=0.04, floor=0.10),
            "rare_token_max_df": min(intish(base.get("rare_token_max_df"), 8) + 2, 14),
            "loose_tfidf_threshold": lower_float(base.get("loose_tfidf_threshold"), default=0.74, step=0.05, floor=0.60),
            "standard_tfidf_threshold": lower_float(base.get("standard_tfidf_threshold"), default=0.86, step=0.04, floor=0.76),
            "multipass_text_top_k": min(intish(base.get("multipass_text_top_k"), 5) + 3, 14),
            "max_candidates_per_job": max(intish(base.get("max_candidates_per_job"), 2000), 3500),
            "max_candidates_per_page": max(intish(base.get("max_candidates_per_page"), 40), 70),
            "sequence_anchor_min_confidence": lower_float(base.get("sequence_anchor_min_confidence"), default=0.86, step=0.04, floor=0.74),
            "sequence_neighbor_window": min(max(intish(base.get("sequence_neighbor_window"), 1), 1) + 1, 2),
            "sequence_min_text_similarity": lower_float(base.get("sequence_min_text_similarity"), default=0.42, step=0.06, floor=0.24),
            "sequence_min_text_similarity_with_visual": lower_float(base.get("sequence_min_text_similarity_with_visual"), default=0.25, step=0.04, floor=0.14),
            "sequence_visual_support_phash_threshold": min(intish(base.get("sequence_visual_support_phash_threshold"), 24) + 4, 36),
        })
        mutations.append(variant)

    if fallback_pressure:
        variant = dict(base)
        variant.update({
            "variant_id": f"loop{iteration:02d}_ocr_budget_expand",
            "planner_reason": "Fallback misses remain; expand OCR page/per-document budget and lower candidate-based OCR acceptance threshold.",
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "ocr_cap": min(intish(base.get("ocr_cap"), 150) + 50, 300),
            "ocr_reason_quotas": "vision_expected:25,weak_tesseract:30,no_text:25,candidate_based:20",
            "openai_ocr_max_pages_per_document": min(intish(base.get("openai_ocr_max_pages_per_document"), 8) + 2, 12),
            "openai_ocr_min_candidate_confidence": lower_float(base.get("openai_ocr_min_candidate_confidence"), default=0.60, step=0.10, floor=0.40),
        })
        mutations.append(variant)

    if semantic_pressure or not counts:
        variant = dict(base)
        variant.update({
            "variant_id": f"loop{iteration:02d}_vector_recall_expand",
            "planner_reason": "Semantic misses remain; widen vector retrieval while preserving deterministic source-safe candidates.",
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "vector_profile": "recall_first",
            "embedding_top_k": min(intish(base.get("embedding_top_k"), 10) + 4, 18),
            "embedding_min_similarity": lower_float(base.get("embedding_min_similarity"), default=0.82, step=0.03, floor=0.74),
            "embedding_min_margin": lower_float(base.get("embedding_min_margin"), default=0.02, step=0.01, floor=0.0),
            "embedding_max_candidates_per_page": min(intish(base.get("embedding_max_candidates_per_page"), 2) + 1, 4),
            "embedding_max_candidates_per_job": max(intish(base.get("embedding_max_candidates_per_job"), 500), 800),
        })
        mutations.append(variant)

    variant = dict(base)
    variant.update({
        "variant_id": f"loop{iteration:02d}_review_acceptance_relax",
        "planner_reason": "Keep discovery broad and test whether queue/acceptance thresholds are hiding candidate pairs from review recall.",
        "cross_view_text_candidates_enabled": True,
        "rare_token_candidates_enabled": True,
        "queue_profile": "recall_first",
        "main_review_min_confidence": lower_float(base.get("main_review_min_confidence"), default=0.86, step=0.08, floor=0.72),
        "main_review_max_candidates_per_100_pages": max(intish(base.get("main_review_max_candidates_per_100_pages"), 50), 100),
        "max_candidates_per_job": max(intish(base.get("max_candidates_per_job"), 2000), 3500),
        "max_candidates_per_page": max(intish(base.get("max_candidates_per_page"), 40), 70),
    })
    mutations.append(variant)

    if aggressive:
        variant = dict(base)
        variant.update({
            "variant_id": f"loop{iteration:02d}_emergency_wide_recall",
            "planner_reason": "Emergency recall mode: accept higher candidate volume to probe whether recall can move toward 0.80 before optimizing noise.",
            "cross_view_text_candidates_enabled": True,
            "rare_token_candidates_enabled": True,
            "ocr_cap": min(intish(base.get("ocr_cap"), 150) + 125, 400),
            "ocr_reason_quotas": "vision_expected:25,weak_tesseract:30,no_text:25,candidate_based:20",
            "openai_ocr_max_pages_per_document": min(intish(base.get("openai_ocr_max_pages_per_document"), 8) + 6, 16),
            "openai_ocr_min_candidate_confidence": lower_float(base.get("openai_ocr_min_candidate_confidence"), default=0.55, step=0.20, floor=0.30),
            "vector_profile": "recall_first",
            "embedding_top_k": min(intish(base.get("embedding_top_k"), 10) + 12, 30),
            "embedding_min_similarity": lower_float(base.get("embedding_min_similarity"), default=0.80, step=0.08, floor=0.68),
            "embedding_min_margin": 0.0,
            "embedding_max_candidates_per_page": min(intish(base.get("embedding_max_candidates_per_page"), 2) + 3, 6),
            "embedding_max_candidates_per_job": max(intish(base.get("embedding_max_candidates_per_job"), 500), 2200),
            "loose_tfidf_threshold": lower_float(base.get("loose_tfidf_threshold"), default=0.70, step=0.15, floor=0.50),
            "standard_tfidf_threshold": lower_float(base.get("standard_tfidf_threshold"), default=0.84, step=0.12, floor=0.68),
            "multipass_text_top_k": min(intish(base.get("multipass_text_top_k"), 8) + 10, 24),
            "rare_token_min_overlap": 2,
            "rare_token_min_jaccard": lower_float(base.get("rare_token_min_jaccard"), default=0.16, step=0.08, floor=0.06),
            "rare_token_max_df": min(intish(base.get("rare_token_max_df"), 10) + 8, 22),
            "sequence_anchor_min_confidence": lower_float(base.get("sequence_anchor_min_confidence"), default=0.82, step=0.12, floor=0.64),
            "sequence_neighbor_window": min(max(intish(base.get("sequence_neighbor_window"), 1), 1) + 2, 3),
            "sequence_min_text_similarity": lower_float(base.get("sequence_min_text_similarity"), default=0.36, step=0.14, floor=0.14),
            "sequence_min_text_similarity_with_visual": lower_float(base.get("sequence_min_text_similarity_with_visual"), default=0.20, step=0.10, floor=0.06),
            "sequence_visual_support_phash_threshold": min(intish(base.get("sequence_visual_support_phash_threshold"), 28) + 12, 44),
            "queue_profile": "recall_first",
            "main_review_min_confidence": lower_float(base.get("main_review_min_confidence"), default=0.84, step=0.20, floor=0.58),
            "main_review_max_candidates_per_100_pages": max(intish(base.get("main_review_max_candidates_per_100_pages"), 50), 260),
            "max_candidates_per_job": max(intish(base.get("max_candidates_per_job"), 2500), 9000),
            "max_candidates_per_page": max(intish(base.get("max_candidates_per_page"), 50), 180),
        })
        mutations.append(variant)
    return mutations


def fallback_variants(iteration: int, aggressive: bool = False) -> list[dict[str, Any]]:
    variants = build_seed_variants(batch_size=7 if aggressive else 5, aggressive=aggressive)
    for index, variant in enumerate(variants, start=1):
        variant = dict(variant)
        variant["variant_id"] = f"loop{iteration:02d}_fallback_{index}_{variant['variant_id']}"
        yield variant


def variants_to_specs(
    variants: list[dict[str, Any]],
    corpora: list[dict[str, str]],
    *,
    iteration: int,
    profile_name: str,
    seen_signatures: set[tuple[Any, ...]],
) -> list[CalibrationRunSpec]:
    specs: list[CalibrationRunSpec] = []
    ordinal = 1
    for variant in variants:
        seen_signatures.add(variant_signature(variant))
        for corpus in corpora:
            specs.append(variant_to_spec(variant, corpus, iteration=iteration, ordinal=ordinal, profile_name=profile_name))
            ordinal += 1
    return specs


def variant_to_spec(variant: dict[str, Any], corpus: dict[str, str], *, iteration: int, ordinal: int, profile_name: str) -> CalibrationRunSpec:
    vector_name = str(variant.get("vector_profile") or "balanced")
    vector = VECTOR_PROFILES.get(vector_name, VECTOR_PROFILES["balanced"])
    variant_id = str(variant.get("variant_id") or f"loop{iteration:02d}_variant{ordinal:02d}")
    corpus_id = str(corpus.get("corpus_id") or "primary")
    run_id = f"loop{iteration:02d}_{ordinal:03d}_{slug(corpus_id)}_{slug(variant_id)}"
    return CalibrationRunSpec(
        run_id=run_id,
        stage="loop",
        profile_name=profile_name,
        ocr_cap=intish(variant.get("ocr_cap"), 150),
        ocr_selection_mode=str(variant.get("ocr_selection_mode") or "reason_balanced"),
        ocr_reason_quotas=str(variant.get("ocr_reason_quotas") or DEFAULT_REASON_QUOTAS),
        vector_profile=vector.name,
        embeddings_enabled=bool(vector.enabled),
        embedding_top_k=intish(variant.get("embedding_top_k"), vector.top_k),
        embedding_min_similarity=floatish(variant.get("embedding_min_similarity"), vector.min_similarity),
        embedding_min_margin=floatish(variant.get("embedding_min_margin"), vector.min_margin),
        embedding_max_candidates_per_page=intish(variant.get("embedding_max_candidates_per_page"), vector.max_candidates_per_page),
        embedding_max_candidates_per_job=intish(variant.get("embedding_max_candidates_per_job"), vector.max_candidates_per_job),
        embedding_min_text_chars=intish(variant.get("embedding_min_text_chars"), vector.min_text_chars),
        queue_profile=str(variant.get("queue_profile") or "recall_first"),
        tesseract_profiles=str(variant.get("tesseract_profiles") or ""),
        openai_ocr_max_pages_per_document=intish(variant.get("openai_ocr_max_pages_per_document"), 8),
        post_candidate_rescue_pages=intish(variant.get("post_candidate_rescue_pages"), 0),
        post_candidate_rescue_min_confidence=floatish(variant.get("post_candidate_rescue_min_confidence"), 0.50),
        embedding_hybrid_scoring=bool(variant.get("embedding_hybrid_scoring", vector.hybrid_scoring)),
        embedding_hybrid_min_score=floatish(variant.get("embedding_hybrid_min_score"), vector.hybrid_min_score),
        corpus_id=corpus_id,
        pdf_dir=str(corpus.get("pdf_dir") or ""),
        truth=str(corpus.get("truth") or ""),
        variant_id=variant_id,
        dpi=variant.get("dpi"),
        ocr_evidence_upgrade_enabled=bool(variant.get("ocr_evidence_upgrade_enabled", True)),
        strict_tfidf_threshold=optional_float(variant.get("strict_tfidf_threshold")),
        standard_tfidf_threshold=optional_float(variant.get("standard_tfidf_threshold")),
        loose_tfidf_threshold=optional_float(variant.get("loose_tfidf_threshold")),
        multipass_text_top_k=optional_int(variant.get("multipass_text_top_k")),
        max_candidates_per_job=optional_int(variant.get("max_candidates_per_job")),
        max_candidates_per_page=optional_int(variant.get("max_candidates_per_page")),
        main_review_min_confidence=optional_float(variant.get("main_review_min_confidence")),
        main_review_max_candidates_per_100_pages=optional_int(variant.get("main_review_max_candidates_per_100_pages")),
        openai_ocr_min_candidate_confidence=optional_float(variant.get("openai_ocr_min_candidate_confidence")),
        sequence_anchor_min_confidence=optional_float(variant.get("sequence_anchor_min_confidence")),
        sequence_neighbor_window=optional_int(variant.get("sequence_neighbor_window")),
        sequence_min_text_similarity=optional_float(variant.get("sequence_min_text_similarity")),
        sequence_min_text_similarity_with_visual=optional_float(variant.get("sequence_min_text_similarity_with_visual")),
        sequence_visual_support_phash_threshold=optional_int(variant.get("sequence_visual_support_phash_threshold")),
        cross_view_text_candidates_enabled=bool(variant.get("cross_view_text_candidates_enabled", True)),
        rare_token_candidates_enabled=bool(variant.get("rare_token_candidates_enabled", True)),
        rare_token_min_overlap=optional_int(variant.get("rare_token_min_overlap")),
        rare_token_min_jaccard=optional_float(variant.get("rare_token_min_jaccard")),
        rare_token_max_df=optional_int(variant.get("rare_token_max_df")),
    )


def row_to_variant(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_id": str(row.get("variant_id") or row.get("run_id") or "base"),
        "ocr_cap": intish(row.get("ocr_cap"), 150),
        "ocr_selection_mode": str(row.get("ocr_selection_mode") or "reason_balanced"),
        "ocr_reason_quotas": str(row.get("ocr_reason_quotas") or DEFAULT_REASON_QUOTAS),
        "vector_profile": str(row.get("embedding_profile") or row.get("vector_profile") or "balanced"),
        "embedding_top_k": intish(row.get("embedding_top_k"), 5),
        "embedding_min_similarity": floatish(row.get("embedding_min_similarity"), 0.85),
        "embedding_min_margin": floatish(row.get("embedding_min_margin"), 0.03),
        "embedding_max_candidates_per_page": intish(row.get("embedding_max_candidates_per_page"), 2),
        "embedding_max_candidates_per_job": intish(row.get("embedding_max_candidates_per_job"), 500),
        "queue_profile": str(row.get("queue_profile") or "balanced"),
        "ocr_evidence_upgrade_enabled": truthy(row.get("ocr_evidence_upgrade_enabled")),
        "openai_ocr_max_pages_per_document": intish(row.get("openai_ocr_max_pages_per_document"), 8),
        "strict_tfidf_threshold": optional_float(row.get("strict_tfidf_threshold")),
        "standard_tfidf_threshold": optional_float(row.get("standard_tfidf_threshold")),
        "loose_tfidf_threshold": optional_float(row.get("loose_tfidf_threshold")),
        "multipass_text_top_k": optional_int(row.get("multipass_text_top_k")),
        "max_candidates_per_job": optional_int(row.get("max_candidates_per_job")),
        "max_candidates_per_page": optional_int(row.get("max_candidates_per_page")),
        "main_review_min_confidence": optional_float(row.get("main_review_min_confidence")),
        "main_review_max_candidates_per_100_pages": optional_int(row.get("main_review_max_candidates_per_100_pages")),
        "openai_ocr_min_candidate_confidence": optional_float(row.get("openai_ocr_min_candidate_confidence")),
        "sequence_anchor_min_confidence": optional_float(row.get("sequence_anchor_min_confidence")),
        "sequence_neighbor_window": optional_int(row.get("sequence_neighbor_window")),
        "sequence_min_text_similarity": optional_float(row.get("sequence_min_text_similarity")),
        "sequence_min_text_similarity_with_visual": optional_float(row.get("sequence_min_text_similarity_with_visual")),
        "sequence_visual_support_phash_threshold": optional_int(row.get("sequence_visual_support_phash_threshold")),
        "cross_view_text_candidates_enabled": truthy(row.get("cross_view_text_candidates_enabled")) if "cross_view_text_candidates_enabled" in row else False,
        "rare_token_candidates_enabled": truthy(row.get("rare_token_candidates_enabled")) if "rare_token_candidates_enabled" in row else False,
        "rare_token_min_overlap": optional_int(row.get("rare_token_min_overlap")),
        "rare_token_min_jaccard": optional_float(row.get("rare_token_min_jaccard")),
        "rare_token_max_df": optional_int(row.get("rare_token_max_df")),
    }


def evaluate_acceptance(
    rows: list[dict[str, Any]],
    *,
    target_metric: str,
    target_recall: float,
    expected_corpus_count: int,
    max_known_negative_hits: Any = None,
    max_unknown_predictions: Any = None,
    max_candidates_per_100_pages: Any = None,
) -> dict[str, Any]:
    ranked = rank_variant_groups(rows, target_metric=target_metric, expected_corpus_count=expected_corpus_count)
    accepted: list[dict[str, Any]] = []
    for group in ranked:
        if expected_corpus_count and int(group.get("corpus_count") or 0) < expected_corpus_count:
            continue
        metric_value = floatish(group.get("worst_metric"), 0.0)
        if metric_value < target_recall:
            continue
        if max_known_negative_hits is not None and floatish(group.get("total_known_negative_hits"), 0.0) > float(max_known_negative_hits):
            continue
        if max_unknown_predictions is not None and floatish(group.get("total_unknown_predictions"), 0.0) > float(max_unknown_predictions):
            continue
        if max_candidates_per_100_pages is not None and floatish(group.get("max_candidates_per_100_pages"), 0.0) > float(max_candidates_per_100_pages):
            continue
        accepted.append(group)
    return {
        "accepted": bool(accepted),
        "target_metric": target_metric,
        "target_recall": target_recall,
        "best_candidate": ranked[0] if ranked else None,
        "accepted_candidate": accepted[0] if accepted else None,
        "accepted_count": len(accepted),
    }


def rank_variant_groups(rows: list[dict[str, Any]], *, target_metric: str, expected_corpus_count: int = 0) -> list[dict[str, Any]]:
    succeeded = [row for row in rows if row.get("status") in {None, "succeeded"}]
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in succeeded:
        variant = str(row.get("variant_id") or row.get("run_id") or "default")
        grouped.setdefault(variant, []).append(row)
    ranked: list[dict[str, Any]] = []
    for variant, group in grouped.items():
        metric_values = [floatish(row.get(target_metric), 0.0) for row in group]
        if not metric_values:
            continue
        best_row = max(group, key=lambda row: floatish(row.get(target_metric), 0.0))
        corpus_ids = sorted({str(row.get("corpus_id") or "unknown") for row in group})
        fn_counts: dict[str, int] = {}
        for row in group:
            for key, value in parse_counts(row.get("false_negative_reason_counts")).items():
                fn_counts[key] = fn_counts.get(key, 0) + int(value)
        total_known_negative = sum(floatish(row.get("known_negative_hits"), 0.0) for row in group)
        total_unknown = sum(floatish(row.get("unknown_predictions"), 0.0) for row in group)
        max_candidates = max((floatish(row.get("candidates_per_100_pages"), 0.0) for row in group), default=0.0)
        avg_metric = sum(metric_values) / len(metric_values)
        worst_metric = min(metric_values)
        score = 500 * worst_metric + 220 * avg_metric - 2.0 * total_known_negative - 0.002 * total_unknown - 0.005 * max_candidates
        if expected_corpus_count and len(corpus_ids) < expected_corpus_count:
            score -= 100
        ranked.append({
            "variant_id": variant,
            "run_count": len(group),
            "corpus_count": len(corpus_ids),
            "corpora": corpus_ids,
            "target_metric": target_metric,
            "avg_metric": round(avg_metric, 4),
            "worst_metric": round(worst_metric, 4),
            "best_metric": round(max(metric_values), 4),
            "score": round(score, 4),
            "total_known_negative_hits": int(total_known_negative),
            "total_unknown_predictions": int(total_unknown),
            "max_candidates_per_100_pages": round(max_candidates, 4),
            "false_negative_reason_counts": fn_counts,
            "best_row": best_row,
        })
    ranked.sort(key=lambda item: (floatish(item.get("worst_metric"), 0.0), floatish(item.get("avg_metric"), 0.0), floatish(item.get("score"), 0.0)), reverse=True)
    return ranked


def read_bootstrap_rows(path_value: str | None) -> list[dict[str, Any]]:
    if not path_value:
        return []
    path = Path(path_value).resolve()
    if not path.exists():
        raise CalibrationLoopError(f"Bootstrap calibration directory does not exist: {path}")
    rows = read_scorecard_rows_from_dir(path)
    if rows:
        return rows

    # v0.10.2+ loop outputs keep scorecards under iteration_* directories, not
    # necessarily at the loop root. Use the full prior loop as bootstrap input
    # so a newer dry-run can seed from the actual long-run evidence pack.
    collected: list[dict[str, Any]] = []
    for scorecard_dir in sorted(path.glob("iteration_*")):
        collected.extend(read_scorecard_rows_from_dir(scorecard_dir))
    return collected


def read_scorecard_rows_from_dir(path: Path) -> list[dict[str, Any]]:
    scorecard_json = read_json(path / "scorecard.json")
    rows = scorecard_json.get("rows") or []
    if rows:
        return list(rows)
    csv_path = path / "scorecard.csv"
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_loop_state(
    out_dir: Path,
    args: Any,
    corpora: list[dict[str, str]],
    iterations: list[dict[str, Any]],
    accepted: dict[str, Any],
    *,
    bootstrap_rows: list[dict[str, Any]] | None = None,
    next_specs: list[CalibrationRunSpec] | None = None,
) -> None:
    write_json(
        out_dir / "calibration_loop_state.json",
        {
            "schema_version": SCHEMA_VERSION,
            "profile": "loop_recall",
            "target_recall": float(getattr(args, "target_recall", DEFAULT_TARGET_RECALL) or DEFAULT_TARGET_RECALL),
            "target_metric": str(getattr(args, "target_metric", "strict_recall") or "strict_recall"),
            "max_iterations": int(getattr(args, "max_iterations", DEFAULT_MAX_ITERATIONS) or DEFAULT_MAX_ITERATIONS),
            "batch_size": int(getattr(args, "batch_size", DEFAULT_BATCH_SIZE) or DEFAULT_BATCH_SIZE),
            "aggressive_search": bool(getattr(args, "aggressive_search", False)),
            "max_parallel_runs": normalized_max_parallel_runs(args),
            "parallel_hard_cap": int(getattr(args, "parallel_hard_cap", DEFAULT_PARALLEL_HARD_CAP) or DEFAULT_PARALLEL_HARD_CAP),
            "corpora": corpora,
            "bootstrap_row_count": len(bootstrap_rows or []),
            "iterations": iterations,
            "accepted": accepted,
            "next_planned_run_count": len(next_specs or []),
            "next_runs": [asdict(spec) for spec in (next_specs or [])],
            "safety": {
                "dry_run": bool(getattr(args, "dry_run", False)),
                "confirm_live_ai": bool(getattr(args, "confirm_live_ai", False)),
                "llm_analysis_enabled": not bool(getattr(args, "no_llm_analysis", False)),
                "metrics_only_default": not bool(getattr(args, "llm_analysis_include_text_snippets", False)),
                "llm_analysis_live": not bool(getattr(args, "no_llm_analysis", False)) and not bool(getattr(args, "llm_analysis_dry_run", False)),
                "llm_analysis_nonfatal": not bool(getattr(args, "fatal_llm_analysis", False)),
                "max_parallel_runs": normalized_max_parallel_runs(args),
                "parallel_hard_cap": int(getattr(args, "parallel_hard_cap", DEFAULT_PARALLEL_HARD_CAP) or DEFAULT_PARALLEL_HARD_CAP),
            },
        },
    )


def build_loop_result(out_dir: Path, *, planned_run_count: int, executed_run_count: int, accepted: dict[str, Any], iterations: list[dict[str, Any]], dry_run: bool, stop_reason: str | None = None) -> dict[str, Any]:
    return {
        "executed": not dry_run,
        "out_dir": str(out_dir),
        "planned_run_count": planned_run_count,
        "executed_run_count": executed_run_count,
        "accepted": accepted,
        "iteration_count": len(iterations),
        "stop_reason": stop_reason,
        "loop_state": str(out_dir / "calibration_loop_state.json"),
        "run_summary_json": str(out_dir / "run_summary.json"),
        "run_summary_md": str(out_dir / "run_summary.md"),
        "decision_log": str(out_dir / "decision_log.jsonl"),
        "timing_log": str(out_dir / "timing.jsonl"),
        "best_config_json": str(out_dir / "best_config.json"),
    }


def variant_signature(variant: dict[str, Any]) -> tuple[Any, ...]:
    keys = [
        "ocr_cap", "ocr_selection_mode", "ocr_reason_quotas", "vector_profile", "embedding_top_k",
        "embedding_min_similarity", "embedding_min_margin", "embedding_max_candidates_per_page",
        "embedding_max_candidates_per_job", "queue_profile", "ocr_evidence_upgrade_enabled",
        "openai_ocr_max_pages_per_document", "openai_ocr_min_candidate_confidence", "strict_tfidf_threshold",
        "standard_tfidf_threshold", "loose_tfidf_threshold", "multipass_text_top_k", "max_candidates_per_job",
        "max_candidates_per_page", "main_review_min_confidence", "main_review_max_candidates_per_100_pages",
        "sequence_anchor_min_confidence", "sequence_neighbor_window", "sequence_min_text_similarity",
        "sequence_min_text_similarity_with_visual", "sequence_visual_support_phash_threshold",
        "cross_view_text_candidates_enabled", "rare_token_candidates_enabled",
        "rare_token_min_overlap", "rare_token_min_jaccard", "rare_token_max_df", "dpi",
    ]
    return tuple((key, normalize_signature_value(variant.get(key))) for key in keys)


def normalize_signature_value(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str) and value.strip() == "":
        return None
    return value


def parse_counts(value: Any) -> dict[str, int]:
    if isinstance(value, dict):
        return {str(key): int(val) for key, val in value.items() if intish(val, 0) != 0}
    if not value:
        return {}
    try:
        data = json.loads(str(value))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key): intish(val, 0) for key, val in data.items()}


def intish(value: Any, default: int) -> int:
    try:
        if value in {None, ""}:
            return int(default)
        return int(float(value))
    except Exception:
        return int(default)


def floatish(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return intish(value, 0)


def optional_float(value: Any) -> float | None:
    if value in {None, ""}:
        return None
    return floatish(value, 0.0)


def lower_float(value: Any, *, default: float, step: float, floor: float) -> float:
    current = floatish(value, default)
    return round(max(floor, current - step), 4)


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y", "on"}
