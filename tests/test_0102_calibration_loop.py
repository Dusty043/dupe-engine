from __future__ import annotations

import argparse
import json
from pathlib import Path

from dupe_engine.calibration_loop import evaluate_acceptance, run_calibration_loop


def make_args(tmp_path: Path, *, bootstrap: Path | None = None, secondary: bool = False) -> argparse.Namespace:
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir(exist_ok=True)
    truth = tmp_path / "truth.json"
    truth.write_text('{"must_match": []}', encoding="utf-8")
    secondary_pdf_dir = None
    secondary_truth = None
    if secondary:
        sec = tmp_path / "pdfs_v4"
        sec.mkdir(exist_ok=True)
        sec_truth = tmp_path / "truth_v4.json"
        sec_truth.write_text('{"must_match": []}', encoding="utf-8")
        secondary_pdf_dir = str(sec)
        secondary_truth = str(sec_truth)
    return argparse.Namespace(
        pdf_dir=str(pdf_dir),
        truth=str(truth),
        out_dir=str(tmp_path / "loop"),
        corpus_id="v3",
        secondary_pdf_dir=secondary_pdf_dir,
        secondary_truth=secondary_truth,
        secondary_corpus_id="v4" if secondary else None,
        bootstrap_calibration_dir=str(bootstrap) if bootstrap else None,
        target_recall=0.80,
        target_metric="strict_recall",
        accept_max_known_negative_hits=None,
        accept_max_unknown_predictions=None,
        accept_max_candidates_per_100_pages=None,
        max_iterations=2,
        batch_size=3,
        max_parallel_runs=2,
        resume=False,
        skip_existing=False,
        retry_failed=False,
        dry_run=True,
        confirm_live_ai=False,
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
    )


def write_bootstrap_calibration(path: Path) -> None:
    path.mkdir(parents=True)
    rows = [
        {
            "run_id": "run_001_v3_baseline",
            "status": "succeeded",
            "corpus_id": "v3",
            "variant_id": "baseline",
            "strict_recall": 0.62,
            "ocr_dependent_recall": 0.53,
            "known_negative_hits": 1,
            "unknown_predictions": 200,
            "candidates_per_100_pages": 48.0,
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "embedding_profile": "balanced",
            "embedding_top_k": 5,
            "embedding_min_similarity": 0.85,
            "embedding_min_margin": 0.03,
            "queue_profile": "balanced",
            "ocr_evidence_upgrade_enabled": True,
            "false_negative_reason_counts": '{"fallback_not_selected": 23, "deterministic_threshold_or_candidate_generation_miss": 9}',
        },
        {
            "run_id": "run_002_v4_baseline",
            "status": "succeeded",
            "corpus_id": "v4",
            "variant_id": "baseline",
            "strict_recall": 0.65,
            "ocr_dependent_recall": 0.63,
            "known_negative_hits": 0,
            "unknown_predictions": 440,
            "candidates_per_100_pages": 126.0,
            "ocr_cap": 150,
            "ocr_selection_mode": "reason_balanced",
            "embedding_profile": "balanced",
            "embedding_top_k": 5,
            "embedding_min_similarity": 0.85,
            "embedding_min_margin": 0.03,
            "queue_profile": "recall_first",
            "ocr_evidence_upgrade_enabled": True,
            "false_negative_reason_counts": '{"fallback_not_selected": 20, "deterministic_threshold_or_candidate_generation_miss": 10}',
        },
    ]
    (path / "scorecard.json").write_text(json.dumps({"rows": rows}), encoding="utf-8")


def test_calibrate_loop_dry_run_writes_first_batch(tmp_path: Path) -> None:
    args = make_args(tmp_path)

    result = run_calibration_loop(args)

    assert result["executed"] is False
    assert result["planned_run_count"] == 3
    state = json.loads((tmp_path / "loop" / "calibration_loop_state.json").read_text(encoding="utf-8"))
    assert state["target_recall"] == 0.8
    assert state["max_parallel_runs"] == 2
    assert state["next_planned_run_count"] == 3
    manifest = json.loads((tmp_path / "loop" / "iteration_01" / "calibration_manifest.json").read_text(encoding="utf-8"))
    assert manifest["planned_run_count"] == 3
    assert all(run["stage"] == "loop" for run in manifest["runs"])


def test_calibrate_loop_bootstrap_plans_next_batch_from_misses(tmp_path: Path) -> None:
    bootstrap = tmp_path / "bootstrap"
    write_bootstrap_calibration(bootstrap)
    args = make_args(tmp_path, bootstrap=bootstrap, secondary=True)

    result = run_calibration_loop(args)

    assert result["executed"] is False
    state = json.loads((tmp_path / "loop" / "calibration_loop_state.json").read_text(encoding="utf-8"))
    assert state["bootstrap_row_count"] == 2
    assert state["next_planned_run_count"] == 6  # 3 generated variants x 2 corpora
    planned = state["next_runs"]
    variant_ids = {run["variant_id"] for run in planned}
    assert any("candidate_threshold_relax" in variant for variant in variant_ids)
    assert any("ocr_budget_expand" in variant for variant in variant_ids)
    assert any(run["cross_view_text_candidates_enabled"] is True for run in planned)
    assert any(run["rare_token_candidates_enabled"] is True for run in planned)
    assert any(run["loose_tfidf_threshold"] is not None for run in planned)
    assert any(run["ocr_cap"] > 150 for run in planned)


def test_acceptance_uses_worst_case_variant_recall() -> None:
    rows = [
        {"status": "succeeded", "variant_id": "good", "corpus_id": "v3", "strict_recall": 0.82, "known_negative_hits": 0, "unknown_predictions": 10},
        {"status": "succeeded", "variant_id": "good", "corpus_id": "v4", "strict_recall": 0.81, "known_negative_hits": 0, "unknown_predictions": 10},
        {"status": "succeeded", "variant_id": "spiky", "corpus_id": "v3", "strict_recall": 0.95, "known_negative_hits": 0, "unknown_predictions": 10},
        {"status": "succeeded", "variant_id": "spiky", "corpus_id": "v4", "strict_recall": 0.50, "known_negative_hits": 0, "unknown_predictions": 10},
    ]

    accepted = evaluate_acceptance(rows, target_metric="strict_recall", target_recall=0.80, expected_corpus_count=2)

    assert accepted["accepted"] is True
    assert accepted["accepted_candidate"]["variant_id"] == "good"
    assert accepted["accepted_candidate"]["worst_metric"] == 0.81


def make_loop_spec(run_id: str, *, corpus_id: str = "v3", variant_id: str = "variant"):
    from dupe_engine.calibration_harness import CalibrationRunSpec

    return CalibrationRunSpec(
        run_id=run_id,
        stage="loop",
        profile_name="loop_recall",
        ocr_cap=150,
        ocr_selection_mode="reason_balanced",
        ocr_reason_quotas="{}",
        vector_profile="balanced",
        embeddings_enabled=True,
        embedding_top_k=5,
        embedding_min_similarity=0.85,
        embedding_min_margin=0.03,
        embedding_max_candidates_per_page=3,
        embedding_max_candidates_per_job=300,
        embedding_min_text_chars=120,
        queue_profile="balanced",
        tesseract_profiles="standard",
        corpus_id=corpus_id,
        pdf_dir="/tmp/pdfs",
        truth="/tmp/truth.json",
        variant_id=variant_id,
        ocr_evidence_upgrade_enabled=True,
    )


def test_parallel_tui_dashboard_renders_aggregate_view(tmp_path: Path, capsys) -> None:
    import time

    from dupe_engine.calibration_harness import render_parallel_progress_dashboard

    iter_dir = tmp_path / "iteration_01"
    spec_a = make_loop_spec("run_001_v3_champion", corpus_id="v3", variant_id="champion")
    spec_b = make_loop_spec("run_002_v4_challenger", corpus_id="v4", variant_id="challenger")
    run_a = iter_dir / "runs" / spec_a.run_id
    run_a.mkdir(parents=True)
    (run_a / "run_status.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (run_a / "progress.json").write_text(
        json.dumps({"stage": "openai_ocr_running", "message": "OpenAI OCR fallback", "current": 5, "total": 10, "percent": 0.5}),
        encoding="utf-8",
    )
    (run_a / "progress_events.jsonl").write_text(
        json.dumps({"stage": "openai_ocr_running", "current": 5, "total": 10, "percent": 0.5}) + "\n",
        encoding="utf-8",
    )

    render_parallel_progress_dashboard(
        iter_dir,
        [spec_a, spec_b],
        iteration=1,
        target_recall=0.8,
        target_metric="strict_recall",
        started=time.time() - 5,
        max_parallel=2,
    )

    output = capsys.readouterr().out
    assert "aggregate parallel TUI" in output
    assert "workers 1/2 active" in output
    assert "run_001_v3_champion" in output
    assert "run_002_v4_challenger" in output
    assert "WAIT" in output


def test_parallel_calibrate_loop_uses_parent_tui_renderer(tmp_path: Path, monkeypatch) -> None:
    import dupe_engine.calibration_loop as loop

    args = make_args(tmp_path)
    args.dry_run = False
    args.confirm_live_ai = True
    args.progress = "tui"
    args.max_parallel_runs = 2
    specs = [make_loop_spec("run_001_v3"), make_loop_spec("run_002_v4", corpus_id="v4")]
    child_modes: list[str] = []
    render_calls: list[bool] = []

    def fake_run_subprocess_with_progress(*_pos, run_dir, spec, progress_mode, **_kwargs):
        child_modes.append(progress_mode)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "progress.json").write_text(
            json.dumps({"stage": "complete", "message": "done", "percent": 1.0}),
            encoding="utf-8",
        )
        return 0

    def fake_build_scorecard_row(spec, run_dir, **_kwargs):
        return {"run_id": spec.run_id, "variant_id": spec.variant_id, "corpus_id": spec.corpus_id, "status": "succeeded", "strict_recall": 0.5}

    def fake_render_parallel_dashboard(*_args, final: bool = False, **_kwargs):
        render_calls.append(final)

    monkeypatch.setattr(loop, "run_subprocess_with_progress", fake_run_subprocess_with_progress)
    monkeypatch.setattr(loop, "build_scorecard_row", fake_build_scorecard_row)
    monkeypatch.setattr(loop, "build_recommendations", lambda rows: {"rows": len(rows)})
    monkeypatch.setattr(loop, "render_parallel_progress_dashboard", fake_render_parallel_dashboard)

    rows = loop.execute_iteration(
        args,
        tmp_path / "iteration_01",
        specs,
        corpora=[],
        iteration=1,
        target_recall=0.8,
        target_metric="strict_recall",
    )

    assert len(rows) == 2
    assert child_modes == ["none", "none"]
    assert render_calls
    assert render_calls[-1] is True


def test_max_parallel_runs_allows_high_stress_cap(tmp_path: Path) -> None:
    import dupe_engine.calibration_loop as loop

    args = make_args(tmp_path)
    args.max_parallel_runs = 10
    args.parallel_hard_cap = 10

    assert loop.normalized_max_parallel_runs(args) == 10

    args.max_parallel_runs = 99
    assert loop.normalized_max_parallel_runs(args) == 10


def test_aggressive_loop_plans_emergency_recall_variants(tmp_path: Path) -> None:
    args = make_args(tmp_path, secondary=True)
    args.batch_size = 7
    args.max_parallel_runs = 10
    args.parallel_hard_cap = 10
    args.aggressive_search = True

    result = run_calibration_loop(args)

    assert result["planned_run_count"] == 14
    state = json.loads((tmp_path / "loop" / "calibration_loop_state.json").read_text(encoding="utf-8"))
    assert state["aggressive_search"] is True
    assert state["max_parallel_runs"] == 10
    variant_ids = {run["variant_id"] for run in state["next_runs"]}
    assert "seed_emergency_wide_recall" in variant_ids
    assert "seed_v4_visual_sequence_sweep" in variant_ids


def test_parallel_tui_dashboard_compacts_large_batches(tmp_path: Path, capsys) -> None:
    import time

    from dupe_engine.calibration_harness import render_parallel_progress_dashboard

    iter_dir = tmp_path / "iteration_01"
    specs = [make_loop_spec(f"run_{index:03d}", corpus_id="v3", variant_id=f"variant_{index}") for index in range(1, 11)]
    run_a = iter_dir / "runs" / specs[0].run_id
    run_a.mkdir(parents=True)
    (run_a / "run_status.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (run_a / "progress.json").write_text(json.dumps({"stage": "ocr", "message": "working", "percent": 0.25}), encoding="utf-8")

    render_parallel_progress_dashboard(
        iter_dir,
        specs,
        iteration=1,
        target_recall=0.8,
        target_metric="strict_recall",
        started=time.time() - 5,
        max_parallel=10,
    )

    output = capsys.readouterr().out
    assert "aggregate parallel TUI" in output
    assert "compact" in output
    assert "workers 1/10 active" in output
    assert "run_010" in output


def test_calibrate_loop_stress_falls_back_after_failed_trial(tmp_path: Path, monkeypatch) -> None:
    import dupe_engine.calibration_loop as loop

    args = make_args(tmp_path)
    args.dry_run = True
    args.out_dir = str(tmp_path / "stress")
    args.parallel_candidates = "10,6"
    args.stress_continue_after_success = False
    args.parallel_hard_cap = 10
    calls: list[int] = []

    def fake_run_calibration_loop(trial_args):
        calls.append(trial_args.max_parallel_runs)
        trial_out = Path(trial_args.out_dir)
        iter_dir = trial_out / "iteration_01"
        iter_dir.mkdir(parents=True)
        status = "failed" if trial_args.max_parallel_runs == 10 else "succeeded"
        (iter_dir / "scorecard.json").write_text(json.dumps({"rows": [{"status": status, "run_id": f"p{trial_args.max_parallel_runs}"}]}), encoding="utf-8")
        return {"executed": False, "out_dir": str(trial_out)}

    monkeypatch.setattr(loop, "run_calibration_loop", fake_run_calibration_loop)

    result = loop.run_calibration_loop_stress(args)

    assert calls == [10, 6]
    assert result["selected_parallel_runs"] == 6
    summary = json.loads((tmp_path / "stress" / "parallel_stress_summary.json").read_text(encoding="utf-8"))
    assert summary["selected_parallel_runs"] == 6
    assert summary["trials"][0]["failed_run_count"] == 1
