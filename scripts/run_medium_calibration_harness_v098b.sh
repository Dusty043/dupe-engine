#!/usr/bin/env bash
set -euo pipefail

: "${DUPE_OPENAI_API_KEY:?Set DUPE_OPENAI_API_KEY before running live calibration}"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir "${DUPE_CALIBRATION_OUT_DIR:-./output/calibration/medium_v098b_accuracy}" \
  --profile "${DUPE_CALIBRATION_PROFILE:-accuracy_first}" \
  --confirm-live-ai \
  "$@"
