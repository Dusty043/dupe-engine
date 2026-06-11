# v0.9.8a Handoff — Calibration Harness Correction

## Purpose

v0.9.8a corrects the v0.9.8 calibration harness after the first live medium calibration run showed that the harness was mechanically working but not yet trustworthy as a recommendation system.

The goal is to make calibration recall-first and control-run-aware.

## Main fixes

1. Added a v0.9.7-style control run as the first default calibration run.
2. Made the recommender score recall-first instead of cost/noise-first.
3. Fixed `reason_balanced` fallback eligibility accounting in fallback audit.
4. Added vector truth-group recall metrics beside exact vector recall.
5. Added false-negative reason counts to the scorecard.
6. Added OCR selection reason counts to the scorecard.
7. Added docs explaining how to interpret the corrected calibration output.

## Why this matters

The first v0.9.8 calibration output recommended the no-OpenAI/no-embedding baseline as `best_by_reviewable_score`, even though recall was only around 0.38. That is not aligned with this project's product priority: false negatives are more costly than extra review candidates.

v0.9.8a keeps low-cost recommendations available, but the main recommendation path is now recall-first.

## Run command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098a \
  --profile balanced \
  --confirm-live-ai
```

Dry run:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098a_dry \
  --profile balanced \
  --max-runs 4 \
  --dry-run
```

## Expected output

```text
output/calibration/medium_v098a/
  calibration_manifest.json
  scorecard.csv
  scorecard.json
  recommended_configs.json
  runs/
    run_001_control_weak_pages_or_vision_expected_cap50_v097_control_balanced/
    ...
```

## How to read recommendations

Start with `control_v097`. If the control run does not roughly reproduce the prior known-good v0.9.7 result, investigate config/harness differences before trusting the sweep.

Then compare:

- `best_by_recall_first_score`
- `best_by_strict_recall`
- `best_by_any_queue_recall`
- `best_reviewable_at_or_above_control`
- `best_low_cost`

For this project, do not pick `best_low_cost` as the product default unless cost is the primary constraint.

## Validation

Unit tests pass:

```text
82 passed
```

A dry-run calibration smoke test confirmed that the control run appears first in the manifest and that the harness writes the v0.9.8a schema.
