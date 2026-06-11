# v0.7.5 Calibration Pass

v0.7.5 is a calibration-first release. It does not make OCR, embeddings, or LLM adjudication mandatory. It improves visibility around the current deterministic engine so threshold tuning can happen before deeper architecture changes.

## What changed

- Added reviewer-facing candidate buckets on every match:
  - `duplicate`
  - `likely_duplicate`
  - `possible_duplicate`
  - `needs_review`
  - `low_information_ignore`
- Added `review_priority` and `review_rationale` to match JSON, candidate JSON, CSV, and HTML outputs.
- Added optional calibration artifacts for `eval-ab` and `eval-all`:
  - calibration JSON
  - candidate summary CSV
  - false-positive / unlabeled prediction review CSV
  - false-negative review CSV
  - threshold sweep CSV
- Added threshold sweep diagnostics to compare recall, known-negative hits, unknown prediction count, and review load per true positive.

## Why this version exists

The medium synthetic corpus is designed to answer:

```text
Can the engine catch duplicate candidates without exploding into useless false positives?
```

The first v0.7 baseline showed that deterministic text catches some duplicates, but the review surface is still noisy. v0.7.5 makes that noise inspectable rather than hiding it inside a single `results.json`.

## Recommended synthetic v2 calibration command

For fast local calibration on the medium corpus, use a lower render DPI first:

```bash
dupe-engine eval-all ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --dpi 72 \
  --max-candidates-per-job 1200 \
  --max-candidates-per-page 25 \
  --out output/synthetic_v2_results.json \
  --eval-out output/synthetic_v2_eval.json \
  --calibration-out output/synthetic_v2_calibration.json \
  --candidate-summary-csv output/synthetic_v2_candidate_summary.csv \
  --false-positive-csv output/synthetic_v2_false_positive_review.csv \
  --false-negative-csv output/synthetic_v2_false_negative_review.csv \
  --threshold-sweep-csv output/synthetic_v2_threshold_sweep.csv \
  --pages-out output/synthetic_v2_pages.json
```

## How to read the artifacts

### Candidate summary

Use this to inspect review queue shape. Sort by:

1. `review_bucket`
2. `review_priority`
3. `confidence`
4. `truth_label` when using synthetic data

The most important thing to watch is whether `possible_duplicate` and `needs_review` are dominated by same-template hard negatives.

### False-positive review

This includes:

- known hard-negative truth hits
- partial-overlap hits
- low-information hits
- unlabeled predictions

`unlabeled_prediction` does not automatically mean false positive. It means the synthetic truth set has no explicit label for the pair, so these rows are used to sample candidate explosion.

### False-negative review

This lists must-match truth pairs that were missed. The `recommended_next_step` column points to the likely next lever:

- OCR tuning for weak/missing text, fax, scan, camera, or degraded pages
- text normalization / top-k tuning for same-text formatting cases
- embedding support for semantic or structurally changed duplicates

### Threshold sweep

This is for calibration tradeoffs. Watch these columns together:

- `recall_on_must_match`
- `known_review_risk_count`
- `unknown_prediction_count`
- `review_load_per_true_positive`

A threshold that improves recall but makes review load explode is not automatically better.

## What v0.7.5 intentionally does not do

- It does not automatically decide final duplicates.
- It does not call embeddings unless embeddings are enabled.
- It does not call LLM detector/adjudicator.
- It does not force OCR into the main path.
- It does not replace reviewer decisions.

The point is to make the next OCR and embedding experiments measurable.
