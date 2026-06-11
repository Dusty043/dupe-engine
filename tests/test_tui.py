from __future__ import annotations

import json
from pathlib import Path

from dupe_engine.tui import (
    BenchmarkOptions,
    build_benchmark_command,
    collect_dashboard_summary,
    quote_command,
)


def test_build_governance_benchmark_command_writes_all_major_artifacts(tmp_path: Path) -> None:
    options = BenchmarkOptions(
        pdf_dir=tmp_path / "pdfs",
        truth_path=tmp_path / "truth.json",
        output_dir=tmp_path / "bench",
        dpi=150,
        profile="governance",
        tesseract_profiles="standard",
    )

    command = build_benchmark_command(options)
    joined = " ".join(command)

    assert command[:3][1:] == ["-m", "dupe_engine.cli"]
    assert "eval-all" in command
    assert str(tmp_path / "bench" / "results.json") in command
    assert str(tmp_path / "bench" / "eval.json") in command
    assert str(tmp_path / "bench" / "calibration.json") in command
    assert str(tmp_path / "bench" / "ocr_validation.json") in command
    assert str(tmp_path / "bench" / "ai_ledger.json") in command
    assert "--ocr" in command
    assert "--openai-ocr" in command
    assert "--openai-ocr-dry-run" in command
    assert "--embeddings" in command
    assert "--embedding-dry-run" in command
    assert "--dpi 150" in joined
    assert "--tesseract-profiles standard" in joined


def test_baseline_benchmark_command_does_not_enable_ocr_or_ai(tmp_path: Path) -> None:
    command = build_benchmark_command(
        BenchmarkOptions(
            pdf_dir=tmp_path / "pdfs",
            truth_path=tmp_path / "truth.json",
            output_dir=tmp_path / "bench",
            profile="baseline",
        )
    )

    assert "--ocr" not in command
    assert "--openai-ocr" not in command
    assert "--embeddings" not in command
    assert "--ai-ledger-out" in command


def test_collect_dashboard_summary_reads_expected_reports(tmp_path: Path) -> None:
    out = tmp_path / "bench"
    out.mkdir()
    (out / "results.json").write_text(json.dumps({"summary": {"total_pages": 10, "match_count": 4}}), encoding="utf-8")
    (out / "eval.json").write_text(json.dumps({"summary": {"recall_on_must_match": 0.5}}), encoding="utf-8")
    (out / "calibration.json").write_text(
        json.dumps({"summary": {"main_review_list_candidate_count": 3}}),
        encoding="utf-8",
    )
    (out / "ocr_validation.json").write_text(
        json.dumps({"summary": {"tesseract_attempted_pages": 2}}),
        encoding="utf-8",
    )
    (out / "ai_ledger.json").write_text(json.dumps({"summary": {"record_count": 1}}), encoding="utf-8")

    summary = collect_dashboard_summary(out)

    assert summary["missing_all"] is False
    assert summary["run"]["total_pages"] == 10
    assert summary["evaluation"]["recall_on_must_match"] == 0.5
    assert summary["calibration"]["main_review_list_candidate_count"] == 3
    assert summary["ocr"]["tesseract_attempted_pages"] == 2
    assert summary["ai_ledger"]["record_count"] == 1


def test_quote_command_handles_paths_with_spaces() -> None:
    rendered = quote_command(["dupe-engine", "eval-all", "folder with spaces"])
    assert "'folder with spaces'" in rendered


def test_benchmark_command_without_truth_omits_truth_flag(tmp_path: Path) -> None:
    command = build_benchmark_command(
        BenchmarkOptions(
            pdf_dir=tmp_path / "pdfs",
            truth_path=None,
            output_dir=tmp_path / "bench",
            profile="governance",
        )
    )

    assert "eval-all" in command
    assert "--truth" not in command
    assert str(tmp_path / "bench" / "eval.json") in command


def test_dashboard_reports_skipped_eval_without_truth(tmp_path: Path) -> None:
    out = tmp_path / "bench"
    out.mkdir()
    (out / "results.json").write_text(
        json.dumps(
            {
                "summary": {"total_pages": 3, "match_count": 1},
                "truth_status": {"available": False, "status": "not_found", "source": "auto_detect"},
            }
        ),
        encoding="utf-8",
    )
    (out / "eval.json").write_text(
        json.dumps(
            {
                "evaluation_available": False,
                "truth_status": {"available": False, "status": "not_found", "source": "auto_detect"},
                "summary": {"predicted_match_count": 1, "recall_on_must_match": None},
            }
        ),
        encoding="utf-8",
    )

    summary = collect_dashboard_summary(out)

    assert summary["evaluation_available"] is False
    assert summary["truth_status"]["status"] == "not_found"
    assert summary["evaluation"]["predicted_match_count"] == 1


def test_ocr_live_profile_enables_provider_without_dry_run_or_embeddings(tmp_path: Path) -> None:
    command = build_benchmark_command(
        BenchmarkOptions(
            pdf_dir=tmp_path / "pdfs",
            truth_path=tmp_path / "truth.json",
            output_dir=tmp_path / "bench",
            profile="ocr-live",
        )
    )

    assert "--ocr" in command
    assert "--openai-ocr" in command
    assert "--openai-ocr-live" in command
    assert "--openai-ocr-dry-run" not in command
    assert "--embeddings" not in command
    assert "--embedding-dry-run" not in command


def test_benchmark_command_can_disable_truth_autodetect(tmp_path: Path) -> None:
    command = build_benchmark_command(
        BenchmarkOptions(
            pdf_dir=tmp_path / "pdfs",
            truth_path=None,
            output_dir=tmp_path / "bench",
            profile="ocr-live",
            truth_autodetect=False,
        )
    )

    assert "--truth" not in command
    assert "--no-truth-autodetect" in command


def test_truth_and_no_truth_rounds_use_separate_output_dirs(tmp_path: Path) -> None:
    from dupe_engine.tui import build_truth_and_no_truth_rounds

    rounds = build_truth_and_no_truth_rounds(
        BenchmarkOptions(
            pdf_dir=tmp_path / "pdfs",
            truth_path=tmp_path / "truth.json",
            output_dir=tmp_path / "bench",
            profile="ocr-live",
        )
    )

    labels = [label for label, _command, _output_dir in rounds]
    assert labels == ["with_truth", "no_truth"]
    with_truth_command = rounds[0][1]
    no_truth_command = rounds[1][1]
    assert str(tmp_path / "bench" / "with_truth" / "results.json") in with_truth_command
    assert "--truth" in with_truth_command
    assert str(tmp_path / "bench" / "no_truth" / "results.json") in no_truth_command
    assert "--truth" not in no_truth_command
    assert "--no-truth-autodetect" in no_truth_command
