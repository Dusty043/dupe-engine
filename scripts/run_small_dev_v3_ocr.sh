#!/usr/bin/env bash
set -euo pipefail

CORPUS_DIR="${CORPUS_DIR:-examples/synthetic_v3/small_dev}"
OUTPUT_DIR="${OUTPUT_DIR:-output/small_dev_v3_ocr}"
RUN_DIR="${RUN_DIR:-output/runs/small_dev_v3_ocr}"
WORK_DIR="${WORK_DIR:-output/work/small_dev_v3_ocr}"
DPI="${DUPE_DPI:-150}"
PROFILES="${DUPE_TESSERACT_PREPROCESSING_PROFILES:-standard}"
OPENAI_OCR_MAX_PAGES="${DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB:-50}"
OPENAI_OCR_SELECTION_MODE="${DUPE_OPENAI_OCR_SELECTION_MODE:-weak_pages_or_vision_expected}"

PYTHONPATH=src python -m dupe_engine.cli eval-all "$CORPUS_DIR" \
  --truth "$CORPUS_DIR/synthetic_v3_truth_pairs.json" \
  --work-dir "$WORK_DIR" \
  --out "$OUTPUT_DIR/results.json" \
  --eval-out "$OUTPUT_DIR/eval.json" \
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
  --tesseract-profiles "$PROFILES"

echo "Run artifacts: $RUN_DIR"
echo "Open review UI: PYTHONPATH=src dupe-engine review-ui --run-dir $RUN_DIR"
