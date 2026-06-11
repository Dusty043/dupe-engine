# v0.9.8b Handoff — Accuracy-First Calibration

v0.9.8b is a corrective calibration release focused on production-facing recall rather than faster iteration.

## What changed

- Added `accuracy_first` calibration profile.
- Added true quota-preserving OpenAI OCR fallback selection.
- Raised the accuracy-first OCR budget candidates to 100 and 150 pages.
- Added `run_status.json` per sub-run.
- Added crash-safe resume behavior.
- Added failed/aborted scorecard rows instead of killing the whole calibration matrix.
- Added `--retry-failed`, `--only-run`, `--fail-fast`, and `--progress` flags.
- Added a lightweight calibration progress TUI.

## Recommended command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_accuracy \
  --profile accuracy_first \
  --confirm-live-ai
```

## Resume after crash

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_accuracy \
  --profile accuracy_first \
  --resume \
  --skip-existing \
  --confirm-live-ai
```

## Retry failed runs

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_accuracy \
  --profile accuracy_first \
  --resume \
  --retry-failed \
  --confirm-live-ai
```

## Run one sub-run only

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_accuracy \
  --profile accuracy_first \
  --only-run run_005_ocr_reason_balanced_cap150_off_balanced \
  --confirm-live-ai
```

## What to inspect

- `scorecard.csv`
- `recommended_configs.json`
- `runs/<run_id>/run_status.json`
- `runs/<run_id>/fallback_audit.json`
- `runs/<run_id>/false_negatives.csv`

## Success target

v0.9.8b should identify whether true quota-balanced fallback at cap 100/150 improves beyond the current control baseline.

Target:

- strict recall above `0.60`
- OCR-dependent recall above `0.50`
- main + secondary recall above current control
- known negative hits still tolerable
- secondary queue accepted as the recall net

