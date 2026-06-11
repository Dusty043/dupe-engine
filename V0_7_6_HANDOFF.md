# Dupe Engine v0.7.6 Handoff

v0.7.6 is a small alignment release between v0.7.5 calibration and v0.8 OCR validation.

It does not introduce live OCR/embedding/adjudicator behavior beyond the existing optional/provider-gated scaffolding. Its purpose is to make the engine output match the v1 product posture before adding heavier accuracy layers.

## Why this release exists

The v1 goalpost says the product is a human-review assist tool, not an automatic duplicate remover. It also defines accepted reviewer labels and says low-information pages should be hidden/separated rather than mixed into the main duplicate queue.

v0.7.5 was useful for calibration, but its schema still blurred three things:

1. engine duplicate-status label,
2. visibility/routing of low-value candidates,
3. future adjudicator and human decisions.

v0.7.6 separates those concepts.

## Main changes

### 1. V1-aligned engine labels

Reviewer-facing engine labels are now:

```text
duplicate
likely_duplicate
possible_duplicate
partial_overlap
needs_review
```

`not_duplicate` is reserved for later adjudicator suggestions and human final decisions.

`low_information_ignore` is no longer a candidate label. It remains valid as a truth/evaluation category.

### 2. V1-shaped candidate fields

`PageMatch` and `CandidateMatch` now include:

```json
{
  "engine_candidate_label": "possible_duplicate",
  "adjudicator_suggested_label": null,
  "human_final_label": null,
  "visibility": "main_review_list",
  "visibility_reason": "candidate has enough non-low-information evidence for the main review list",
  "candidate_category": "standard"
}
```

The old `review_bucket` field is retained as a compatibility alias for `engine_candidate_label`.

### 3. Visibility routing

Candidates can now be routed as:

```text
main_review_list
low_information
calibration_only
```

Default behavior:

- exact/strict/standard useful candidates go to `main_review_list`,
- low-information candidates go to `low_information`,
- loose/borderline candidates below the main-list confidence band go to `calibration_only`, and main-list overflow above the default workload budget is also routed to `calibration_only`.

The default main-list confidence band and workload budget are controlled by:

```bash
DUPE_MAIN_REVIEW_MIN_CONFIDENCE=0.86
DUPE_MAIN_REVIEW_MAX_CANDIDATES_PER_100_PAGES=50
```

or:

```bash
--main-review-min-confidence 0.86
--main-review-max-candidates-per-100-pages 50
```

### 4. Calibration outputs now show review load more clearly

Calibration JSON/CSV now includes:

- `engine_candidate_label`
- `visibility`
- `visibility_reason`
- `candidate_category`
- main-review candidate counts
- low-information candidate counts
- calibration-only candidate counts
- candidate pairs per 100 pages
- main-review candidate pairs per 100 pages

This lets calibration track both raw detector behavior and the default Sorter/Organizer workload.

## What this release intentionally does not solve

v0.7.6 does not try to hit the final v1 accuracy target.

It does not yet make scanned duplicates work well. That is v0.8 OCR validation.

It does not yet use live embeddings to rerank borderline semantic candidates. That is v0.9.

It does not yet run a real adjudicator. That is v0.10.

It does not yet provide the non-technical UI, saved review decisions, or audit history. That is v0.11+.

## Validation

Run unit tests:

```bash
PYTHONPATH=src pytest -q
```

Run a medium synthetic calibration pass:

```bash
PYTHONPATH=src python -m dupe_engine.cli eval-all ../corpus/pdfs \
  --truth ../corpus/synthetic_v2_truth_pairs.json \
  --dpi 72 \
  --work-dir output/work_synthetic_v2_dpi72 \
  --out output/synthetic_v2_results.json \
  --eval-out output/synthetic_v2_eval.json \
  --csv output/synthetic_v2_matches.csv \
  --calibration-out output/synthetic_v2_calibration.json \
  --candidate-summary-csv output/synthetic_v2_candidate_summary.csv \
  --false-positive-csv output/synthetic_v2_false_positive_review.csv \
  --false-negative-csv output/synthetic_v2_false_negative_review.csv \
  --threshold-sweep-csv output/synthetic_v2_threshold_sweep.csv \
  --pages-out output/synthetic_v2_pages.json
```

## Next release

v0.8 should validate OCR as an accuracy layer:

```text
native PDF text
-> Tesseract cheap OCR
-> selected OpenAI OCR fallback
-> OCR route metrics
-> OCR-dependent recall report
```
