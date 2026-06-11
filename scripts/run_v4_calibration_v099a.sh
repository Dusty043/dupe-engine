#!/usr/bin/env bash
set -euo pipefail

: "${DUPE_OPENAI_API_KEY:?Set DUPE_OPENAI_API_KEY before running live v4 calibration}"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v4_calibration \
  --truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --out-dir ./output/calibration/v4_v099a \
  --profile v4_calibration \
  --confirm-live-ai
