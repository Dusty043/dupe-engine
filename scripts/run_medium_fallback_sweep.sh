#!/usr/bin/env bash
set -euo pipefail

CORPUS_DIR="${CORPUS_DIR:-examples/synthetic_v3/medium_calibration}"
BASE_OUTPUT_DIR="${BASE_OUTPUT_DIR:-output/fallback_sweep_medium}"
DPI="${DUPE_DPI:-150}"
PROFILES="${DUPE_TESSERACT_PREPROCESSING_PROFILES:-standard}"
SELECTION_MODE="${DUPE_OPENAI_OCR_SELECTION_MODE:-weak_pages_or_vision_expected}"
CAPS="${CAPS:-0 25 50 100}"
PER_DOC_CAP="${DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT:-5}"

mkdir -p "$BASE_OUTPUT_DIR"
SUMMARY_CSV="$BASE_OUTPUT_DIR/sweep_summary.csv"
echo "cap,recall,true_positive_count,false_negative_count,selected,attempted,usable,improved,eligible_not_selected,results_dir,run_dir" > "$SUMMARY_CSV"

for CAP in $CAPS; do
  OUT_DIR="$BASE_OUTPUT_DIR/cap_${CAP}"
  RUN_DIR="$OUT_DIR/run"
  WORK_DIR="$OUT_DIR/work"
  mkdir -p "$OUT_DIR"
  echo "=== Running medium fallback cap $CAP ==="
  PYTHONPATH=src python -m dupe_engine.cli eval-all "$CORPUS_DIR" \
    --truth "$CORPUS_DIR/synthetic_v3_truth_pairs.json" \
    --work-dir "$WORK_DIR" \
    --out "$OUT_DIR/results.json" \
    --eval-out "$OUT_DIR/eval.json" \
    --progress-dir "$RUN_DIR" \
    --fallback-audit-out "$OUT_DIR/fallback_audit.json" \
    --fallback-audit-csv "$OUT_DIR/fallback_pages.csv" \
    --ocr-validation-out "$OUT_DIR/ocr_validation.json" \
    --ocr-route-csv "$OUT_DIR/ocr_routes.csv" \
    --ocr-candidate-csv "$OUT_DIR/ocr_candidates.csv" \
    --run-dir "$RUN_DIR" \
    --dpi "$DPI" \
    --ocr \
    --require-ocr \
    --openai-ocr \
    --openai-ocr-live \
    --require-openai-ocr \
    --openai-ocr-max-pages "$CAP" \
    --openai-ocr-max-pages-per-document "$PER_DOC_CAP" \
    --openai-ocr-selection-mode "$SELECTION_MODE" \
    --tesseract-profiles "$PROFILES"

  python - <<PY
import json, pathlib
out = pathlib.Path("$OUT_DIR")
eval_summary = json.loads((out / "eval.json").read_text()).get("summary", {})
fallback_summary = json.loads((out / "fallback_audit.json").read_text()).get("summary", {})
row = [
    "$CAP",
    eval_summary.get("recall_on_must_match", ""),
    eval_summary.get("true_positive_count", ""),
    eval_summary.get("false_negative_count", ""),
    fallback_summary.get("selected_pages", ""),
    fallback_summary.get("attempted_pages", ""),
    fallback_summary.get("usable_pages", ""),
    fallback_summary.get("improved_pages", ""),
    fallback_summary.get("eligible_not_selected_pages", ""),
    str(out),
    str(out / "run"),
]
with open("$SUMMARY_CSV", "a", encoding="utf-8") as f:
    f.write(",".join(map(str,row)) + "\n")
PY
done

echo "Sweep summary: $SUMMARY_CSV"
