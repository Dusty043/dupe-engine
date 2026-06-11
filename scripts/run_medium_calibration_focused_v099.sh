#!/usr/bin/env bash
set -euo pipefail

: "${DUPE_OPENAI_API_KEY:?Set DUPE_OPENAI_API_KEY before running live calibration}"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v099_focused \
  --profile focused_rescue \
  --confirm-live-ai \
  "$@"
