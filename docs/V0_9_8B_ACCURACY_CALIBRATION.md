# v0.9.8b Accuracy Calibration Notes

v0.9.8b changes the calibration goal from fast iteration to highest useful recall.

## Why

The duplicate checker is human-reviewed. False positives are review burden; false negatives are missed duplicates. Therefore calibration should prioritize recall and then route lower-confidence candidates into secondary/calibration queues.

## Accuracy-first matrix

The `accuracy_first` profile keeps the v0.9.7 control run, then focuses on:

- no-fallback baseline
- cap 100 OCR rescue
- cap 150 OCR rescue
- conservative, balanced, and recall-first vector profiles
- strict, balanced, and recall-first queue profiles

## True quota-balanced fallback

`reason_balanced` now preserves the bucket that selected a page. Quotas reserve budget across:

- `candidate_based`
- `vision_expected`
- `weak_tesseract`
- `no_text`

Pages can be eligible for multiple buckets, but once selected, the audit reason is not overwritten by a later higher-scored overlapping reason. This makes `openai_ocr_selection_reason_counts` useful for validating budget allocation.

## Progress TUI

The calibration harness polls each sub-run's `progress.json` and displays:

- current run index
- run id
- OCR/vector/queue profile
- engine stage
- current/total page progress, when available
- elapsed time

Use `--progress plain` for log-friendly output and `--progress none` for quiet runs.

## Crash-safe resume

Each run writes `run_status.json` with `running`, `succeeded`, `failed`, or `aborted` status.

On resume:

- completed runs are skipped with `--resume` or `--skip-existing`
- previously running runs are marked `aborted`
- failed/aborted runs are carried into the scorecard unless `--retry-failed` is supplied
- failed sub-runs do not kill the matrix unless `--fail-fast` is supplied

