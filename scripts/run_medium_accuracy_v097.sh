#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-"$SCRIPT_DIR/../.venv/bin/python"}"

CORPUS_DIR="${CORPUS_DIR:-examples/synthetic_v3/medium_calibration}"
OUTPUT_DIR="${OUTPUT_DIR:-output/medium_calibration_v3_ocr_vector}"
RUN_DIR="${RUN_DIR:-output/runs/medium_calibration_v3_ocr_vector}"
WORK_DIR="${WORK_DIR:-output/work/medium_calibration_v3_ocr_vector}"
DPI="${DUPE_DPI:-150}"
PROFILES="${DUPE_TESSERACT_PREPROCESSING_PROFILES:-standard}"
OPENAI_OCR_MAX_PAGES="${DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB:-50}"
OPENAI_OCR_MAX_PAGES_PER_DOCUMENT="${DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT:-5}"
OPENAI_OCR_SELECTION_MODE="${DUPE_OPENAI_OCR_SELECTION_MODE:-weak_pages_or_vision_expected}"
TESSERACT_MIN_WORDS="${DUPE_TESSERACT_MIN_WORDS:-20}"
EMBEDDING_TOP_K="${DUPE_EMBEDDINGS_CANDIDATE_TOP_K:-5}"
EMBEDDING_THRESHOLD="${DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD:-0.88}"
EMBEDDING_MIN_MARGIN="${DUPE_EMBEDDINGS_MIN_MARGIN:-0.03}"
EMBEDDING_MAX_PAGES="${DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB:-1000}"
EMBEDDING_MAX_PER_PAGE="${DUPE_EMBEDDINGS_MAX_CANDIDATES_PER_PAGE:-2}"

PYTHONPATH=src "$PYTHON" -m dupe_engine.cli eval-all "$CORPUS_DIR" \
  --truth "$CORPUS_DIR/synthetic_v3_truth_pairs.json" \
  --work-dir "$WORK_DIR" \
  --out "$OUTPUT_DIR/results.json" \
  --eval-out "$OUTPUT_DIR/eval.json" \
  --phase-eval-out "$OUTPUT_DIR/phase_eval.json" \
  --progress-dir "$RUN_DIR" \
  --fallback-audit-out "$OUTPUT_DIR/fallback_audit.json" \
  --fallback-audit-csv "$OUTPUT_DIR/fallback_pages.csv" \
  --ocr-validation-out "$OUTPUT_DIR/ocr_validation.json" \
  --ocr-route-csv "$OUTPUT_DIR/ocr_routes.csv" \
  --ocr-candidate-csv "$OUTPUT_DIR/ocr_candidates.csv" \
  --run-dir "$RUN_DIR" \
  --dpi "$DPI" \
  --ocr \
  --require-ocr \
  --openai-ocr \
  --openai-ocr-live \
  --require-openai-ocr \
  --openai-ocr-max-pages "$OPENAI_OCR_MAX_PAGES" \
  --openai-ocr-max-pages-per-document "$OPENAI_OCR_MAX_PAGES_PER_DOCUMENT" \
  --openai-ocr-selection-mode "$OPENAI_OCR_SELECTION_MODE" \
  --tesseract-profiles "$PROFILES" \
  --tesseract-min-words "$TESSERACT_MIN_WORDS" \
  --embeddings \
  --embedding-top-k "$EMBEDDING_TOP_K" \
  --embedding-similarity-threshold "$EMBEDDING_THRESHOLD" \
  --embedding-min-margin "$EMBEDDING_MIN_MARGIN" \
  --embedding-max-pages "$EMBEDDING_MAX_PAGES" \
  --embedding-max-candidates-per-page "$EMBEDDING_MAX_PER_PAGE"

echo "Run artifacts: $RUN_DIR"
echo "Phase eval: $OUTPUT_DIR/phase_eval.json"
echo "Open review UI: PYTHONPATH=src dupe-engine review-ui --run-dir $RUN_DIR"
