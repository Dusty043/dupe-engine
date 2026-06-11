#!/usr/bin/env bash
set -euo pipefail

# Run from inside the container, or from a host with the same /data mounts.
# Default server posture: p6 sustained, p4 fallback is a manual rerun choice,
# p10 remains a stress/emergency ceiling.

OUT_DIR="${OUT_DIR:-/data/runs/loop_v0107_server_p6_$(date +%Y%m%d_%H%M%S)}"
BOOTSTRAP_DIR="${BOOTSTRAP_DIR:-/data/runs/bootstrap/loop_v0106_emergency_p10}"

exec dupe-engine continuous-calibration \
  /data/corpora/synthetic_v3/medium_calibration \
  --truth /data/truth/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir /data/corpora/synthetic_v4_calibration \
  --secondary-truth /data/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir "$BOOTSTRAP_DIR" \
  --out-dir "$OUT_DIR" \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 6 \
  --parallel-hard-cap 10 \
  --max-total-runtime-hours 24 \
  --max-iteration-runtime-hours 3 \
  --max-run-dir-gb 25 \
  --min-free-disk-gb 40 \
  --max-openai-ocr-pages 10000 \
  --max-embedding-calls 50000 \
  --max-llm-analysis-calls 50 \
  --max-best-unknown-predictions 15000 \
  --max-best-known-negative-hits 50 \
  --max-plateau-iterations 3 \
  --min-recall-gain 0.01 \
  --aggressive-search \
  --prune-artifacts analysis-only \
  --progress tui \
  --confirm-live-ai
