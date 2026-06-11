from __future__ import annotations

import argparse
import json
from pathlib import Path

import dupe_engine.calibration_loop as loop
from dupe_engine.calibration_observability import evaluate_guardrails, prune_calibration_artifacts


def make_args(tmp_path: Path) -> argparse.Namespace:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(exist_ok=True)
    truth = tmp_path / "truth.json"
    truth.write_text('{"must_match": []}', encoding="utf-8")
    return argparse.Namespace(
        pdf_dir=str(pdf_dir),
        truth=str(truth),
        out_dir=str(tmp_path / "loop"),
        corpus_id="v3",
        secondary_pdf_dir=None,
        secondary_truth=None,
        secondary_corpus_id=None,
        bootstrap_calibration_dir=None,
        target_recall=0.80,
        target_metric="strict_recall",
        accept_max_known_negative_hits=None,
        accept_max_unknown_predictions=None,
        accept_max_candidates_per_100_pages=None,
        max_iterations=3,
        batch_size=2,
        aggressive_search=False,
        max_parallel_runs=1,
        parallel_hard_cap=10,
        resume=False,
        skip_existing=False,
        retry_failed=False,
        dry_run=False,
        confirm_live_ai=True,
        dpi=150,
        tesseract_profiles="standard",
        progress="none",
        fail_fast=False,
        no_llm_analysis=True,
        llm_analysis_dry_run=True,
        llm_analysis_include_text_snippets=False,
        llm_analysis_model=None,
        llm_analysis_out=None,
        llm_analysis_json_out=None,
        fatal_llm_analysis=False,
        prune_artifacts="analysis-only",
        prune_dry_run=False,
        max_total_runtime_hours=None,
        max_iteration_runtime_hours=None,
        max_run_dir_gb=None,
        min_free_disk_gb=None,
        max_openai_ocr_pages=None,
        max_embedding_calls=None,
        max_llm_analysis_calls=None,
        max_unknown_predictions_total=None,
        max_known_negative_hits_total=None,
        max_best_unknown_predictions=None,
        max_best_known_negative_hits=None,
        max_plateau_iterations=1,
        min_recall_gain=0.01,
    )


def test_prune_artifacts_analysis_only_keeps_evidence(tmp_path: Path) -> None:
    run_dir = tmp_path / "iteration_01"
    run_dir.mkdir()
    (run_dir / "scorecard.json").write_text('{"rows": []}', encoding="utf-8")
    (run_dir / "scorecard.csv").write_text("run_id\n", encoding="utf-8")
    (run_dir / "notes.md").write_text("# notes\n", encoding="utf-8")
    (run_dir / "command.txt").write_text("dupe-engine ...\n", encoding="utf-8")
    (run_dir / "stdout.log").write_text("large log\n", encoding="utf-8")
    (run_dir / "page.png").write_bytes(b"not really an image")
    nested = run_dir / "debug" / "images"
    nested.mkdir(parents=True)
    (nested / "page.webp").write_bytes(b"debug image")

    result = prune_calibration_artifacts(run_dir, mode="analysis-only", dry_run=False, require_summary=True)

    assert result["status"] == "applied"
    assert (run_dir / "scorecard.json").exists()
    assert (run_dir / "scorecard.csv").exists()
    assert (run_dir / "notes.md").exists()
    assert (run_dir / "command.txt").exists()
    assert not (run_dir / "stdout.log").exists()
    assert not (run_dir / "page.png").exists()
    assert not nested.exists()
    assert (run_dir / "artifact_prune_report.json").exists()


def test_guardrail_stops_on_openai_ocr_budget(tmp_path: Path) -> None:
    args = make_args(tmp_path)
    args.max_openai_ocr_pages = 10
    rows = [
        {"status": "succeeded", "variant_id": "v", "corpus_id": "v3", "strict_recall": 0.5, "openai_ocr_attempted": 6},
        {"status": "succeeded", "variant_id": "v", "corpus_id": "v3", "strict_recall": 0.5, "openai_ocr_attempted": 7},
    ]

    result = evaluate_guardrails(
        args,
        out_dir=tmp_path,
        all_rows=rows,
        started_monotonic=0.0,
        iteration_elapsed_seconds=0.0,
        plateau_count=0,
        llm_analysis_calls=0,
        target_metric="strict_recall",
        expected_corpus_count=1,
    )

    assert result.triggered is True
    assert result.stop_reason == "paused_cost_limit"
    assert result.metrics["openai_ocr_attempted"] == 13


def test_loop_writes_decision_timing_summary_and_stops_on_plateau(tmp_path: Path, monkeypatch) -> None:
    args = make_args(tmp_path)

    def fake_execute_iteration(_args, _iter_dir, specs, *_pos, **_kwargs):
        return [
            {
                "run_id": spec.run_id,
                "variant_id": spec.variant_id,
                "corpus_id": spec.corpus_id,
                "status": "succeeded",
                "strict_recall": 0.50,
                "known_negative_hits": 0,
                "unknown_predictions": 10,
                "openai_ocr_attempted": 2,
                "embedding_calls": 3,
                "candidates_per_100_pages": 5.0,
            }
            for spec in specs
        ]

    monkeypatch.setattr(loop, "execute_iteration", fake_execute_iteration)

    result = loop.run_calibration_loop(args)

    out_dir = Path(result["out_dir"])
    assert result["stop_reason"] == "stopped_plateau"
    assert (out_dir / "decision_log.jsonl").exists()
    assert (out_dir / "timing.jsonl").exists()
    assert (out_dir / "run_summary.json").exists()
    assert (out_dir / "run_summary.md").exists()
    assert (out_dir / "best_config.json").exists()
    summary = json.loads((out_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "stopped_plateau"
    assert summary["usage"]["openai_ocr_attempted"] > 0
    decisions = (out_dir / "decision_log.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(decisions) == 2
    assert json.loads(decisions[-1])["stop_reason"] == "stopped_plateau"
