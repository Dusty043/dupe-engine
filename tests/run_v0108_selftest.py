#!/usr/bin/env python3
"""Tiny self-test runner that does not require pytest."""
from __future__ import annotations

import csv
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dupe_engine.calibration_diagnostics_v0108 import build_diagnostics


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    root = Path(tempfile.mkdtemp(prefix="v0108_selftest_"))
    try:
        run_dir = root / "run"
        run_dir.mkdir()
        (run_dir / "run_summary.json").write_text(json.dumps({
            "status": "stopped_plateau",
            "stop_reason": "stopped_plateau",
            "target_metric": "strict_recall",
            "target_recall": 0.8,
            "iteration_count": 1,
            "usage": {"total_runtime_seconds": 1800, "openai_ocr_attempted": 20, "embedding_calls": 40, "llm_analysis_calls": 1},
            "best_candidate": {
                "variant_id": "loop02_prior_champion",
                "worst_metric": 0.6,
                "avg_metric": 0.62,
                "false_negative_reason_counts": {"ocr_or_vision_layer_miss": 10},
                "best_row": {"run_id": "loop02_001_v3_loop02_prior_champion", "variant_id": "loop02_prior_champion"},
            },
        }), encoding="utf-8")
        (run_dir / "decision_log.jsonl").write_text(json.dumps({"iteration": 1, "iteration_run_count": 2, "plateau_count": 1}) + "\n", encoding="utf-8")
        write_csv(run_dir / "scorecard.csv", [
            {"run_id":"loop01_001_v3_loop01_new","variant_id":"loop01_new","corpus_id":"v3","strict_recall":"0.55","status":"succeeded","unknown_predictions":"10","known_negative_hits":"0","candidates_per_100_pages":"100","runtime_seconds":"10","openai_ocr_attempted":"1","embedding_calls":"2","false_negative_reason_counts":"{}","openai_ocr_selection_reason_counts":"{}","reused":"False"},
            {"run_id":"loop01_002_v4_loop01_new","variant_id":"loop01_new","corpus_id":"v4","strict_recall":"0.50","status":"succeeded","unknown_predictions":"11","known_negative_hits":"1","candidates_per_100_pages":"120","runtime_seconds":"12","openai_ocr_attempted":"1","embedding_calls":"2","false_negative_reason_counts":"{}","openai_ocr_selection_reason_counts":"{}","reused":"False"},
        ])
        d = build_diagnostics(run_dir)
        assert d["global_best_source"] == "inherited_or_bootstrap", d["global_best_source"]
        assert d["current_best"]["variant_id"] == "loop01_new", d["current_best"]
        print("v0.10.8 diagnostics self-test passed")
        return 0
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
