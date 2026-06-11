# v0.9.9a V4 Calibration and Terminal Progress

## Summary

v0.9.9a makes two changes:

1. Adds the `synthetic_v4_calibration` corpus and a five-run v4 calibration matrix.
2. Improves calibration progress display with a cleaner multi-bar terminal dashboard.

## Why v4 calibration exists

The v3 medium corpus exposed the major engine bottlenecks, but repeated tuning began to flatten around the same recall ceiling. The v4 calibration corpus is a fresh tuning corpus with a more realistic `received_records` vs `ere_records` shape and explicit layer tags.

## Five-run v4 matrix

The profile is:

```bash
--profile v4_calibration
```

Runs:

| Run | OCR cap | Vector | Rescue | Purpose |
|---|---:|---|---:|---|
| 1 | 150 | conservative | 0 | Current best baseline transfer test |
| 2 | 225 | conservative | 0 | Test whether first-pass OCR is still too conservative |
| 3 | 150 | conservative | 50 | Test targeted rescue instead of higher first-pass budget |
| 4 | 225 | conservative | 25 | Test higher first-pass OCR plus small rescue reserve |
| 5 | 225 | balanced | 0 | Test whether v4 needs broader vector retrieval |

Hybrid vector is intentionally excluded from the first v4 matrix because it did not beat conservative vector on v3.

## Progress dashboard

Default:

```bash
--progress tui
```

Fallback:

```bash
--progress plain
```

Quiet:

```bash
--progress none
```

The dashboard is display-only. Each sub-run still writes normal artifacts:

```text
runs/<run_id>/progress.json
runs/<run_id>/progress_events.jsonl
runs/<run_id>/stdout.log
runs/<run_id>/stderr.log or stdout-combined log
runs/<run_id>/run_status.json
```

## Metrics to inspect first

```text
strict_recall
main_or_secondary_recall
ocr_dependent_recall
true_positives
false_negatives
known_negative_hits
unknown_predictions
openai_ocr_selection_reason_counts
false_negative_reason_counts
main_queue_size
secondary_queue_size
```

## Success criteria

For a fresh v4 calibration corpus, initial success is:

```text
strict recall >= 0.70
OCR-dependent recall >= 0.55
known negatives controlled
main + secondary queue reviewable
```

Stretch target:

```text
strict recall near 0.80
```

Do not tune the holdout until v4 calibration produces a candidate default.
