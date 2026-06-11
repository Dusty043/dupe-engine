#!/usr/bin/env bash
set -euo pipefail

: "${DUPE_OPENAI_API_KEY:?Set DUPE_OPENAI_API_KEY before running live calibration}"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/generalization_v099b \
  --profile generalization \
  --confirm-live-ai
