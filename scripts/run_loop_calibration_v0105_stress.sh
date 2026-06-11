#!/usr/bin/env bash
set -euo pipefail

: "${DUPE_OPENAI_API_KEY:?Set DUPE_OPENAI_API_KEY before running live calibration}"

PYTHONPATH=src python -m dupe_engine.cli calibrate-loop-stress \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0104 \
  --out-dir ./output/calibration/loop_v0105_stress \
  --target-recall 0.80 \
  --batch-size 5 \
  --max-iterations "${DUPE_LOOP_MAX_ITERATIONS:-1}" \
  --parallel-candidates "${DUPE_LOOP_PARALLEL_CANDIDATES:-10,6}" \
  --aggressive-search \
  --progress tui \
  --confirm-live-ai
