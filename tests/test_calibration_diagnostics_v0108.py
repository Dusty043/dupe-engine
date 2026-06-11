from __future__ import annotations

import csv
import json
from pathlib import Path

from dupe_engine.calibration_diagnostics_v0108 import build_diagnostics, variant_family, loop_index


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def test_loop_index_and_family() -> None:
    assert loop_index("loop04_003_v3_medium_loop04_ocr_budget_expand") == 4
    assert loop_index("not_loop") is None
    assert variant_family("loop04_ocr_budget_expand") == "ocr_budget_expand"
    assert variant_family("ocr_budget_expand") == "ocr_budget_expand"


def test_bootstrap_champion_detection(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_summary.json").write_text(
        json.dumps(
            {
                "status": "stopped_plateau",
                "stop_reason": "stopped_plateau",
                "target_metric": "strict_recall",
                "target_recall": 0.8,
                "iteration_count": 3,
                "usage": {"total_runtime_seconds": 3600, "openai_ocr_attempted": 100, "embedding_calls": 200, "llm_analysis_calls": 1},
                "best_candidate": {
                    "variant_id": "loop04_ocr_budget_expand",
                    "worst_metric": 0.60,
                    "avg_metric": 0.62,
                    "false_negative_reason_counts": {"ocr_or_vision_layer_miss": 5, "fallback_not_selected": 2},
                    "best_row": {"run_id": "loop04_001_v3_loop04_ocr_budget_expand", "variant_id": "loop04_ocr_budget_expand"},
                },
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "decision_log.jsonl").write_text(
        json.dumps({"iteration": 1, "iteration_run_count": 2, "best_metric_gain": 0.0, "plateau_count": 1}) + "\n"
        + json.dumps({"iteration": 2, "iteration_run_count": 2, "best_metric_gain": 0.0, "plateau_count": 2}) + "\n"
        + json.dumps({"iteration": 3, "iteration_run_count": 2, "best_metric_gain": 0.0, "plateau_count": 3, "stop_reason": "stopped_plateau"}) + "\n",
        encoding="utf-8",
    )
    _write_csv(
        run_dir / "scorecard.csv",
        [
            {
                "run_id": "loop01_001_v3_loop01_candidate",
                "variant_id": "loop01_candidate",
                "corpus_id": "v3",
                "strict_recall": 0.55,
                "status": "succeeded",
                "unknown_predictions": 10,
                "known_negative_hits": 0,
                "candidates_per_100_pages": 100,
                "runtime_seconds": 10,
                "openai_ocr_attempted": 1,
                "embedding_calls": 2,
                "false_negative_reason_counts": '{"ocr_or_vision_layer_miss": 3}',
                "openai_ocr_selection_reason_counts": '{}',
                "reused": "False",
            },
            {
                "run_id": "loop01_002_v4_loop01_candidate",
                "variant_id": "loop01_candidate",
                "corpus_id": "v4",
                "strict_recall": 0.50,
                "status": "succeeded",
                "unknown_predictions": 11,
                "known_negative_hits": 1,
                "candidates_per_100_pages": 120,
                "runtime_seconds": 12,
                "openai_ocr_attempted": 1,
                "embedding_calls": 2,
                "false_negative_reason_counts": '{"fallback_not_selected": 1}',
                "openai_ocr_selection_reason_counts": '{}',
                "reused": "False",
            },
            {
                "run_id": "loop04_001_v3_loop04_ocr_budget_expand",
                "variant_id": "loop04_ocr_budget_expand",
                "corpus_id": "v3",
                "strict_recall": 0.64,
                "status": "succeeded",
                "unknown_predictions": 20,
                "known_negative_hits": 2,
                "candidates_per_100_pages": 220,
                "runtime_seconds": 20,
                "openai_ocr_attempted": 2,
                "embedding_calls": 4,
                "false_negative_reason_counts": '{}',
                "openai_ocr_selection_reason_counts": '{}',
                "reused": "False",
            },
        ],
    )
    d = build_diagnostics(run_dir)
    assert d["global_best_source"] == "inherited_or_bootstrap"
    assert d["current_best"]["variant_id"] == "loop01_candidate"
    assert d["throughput"]["runs_per_hour"] == 6.0
    assert d["dominant_false_negative_reason"]["reason"] == "ocr_or_vision_layer_miss"
