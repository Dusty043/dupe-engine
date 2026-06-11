# Dupe Engine v0.7.5 Handoff

## Release intent

v0.7.5 is the calibration pass before OCR/embedding expansion. It keeps the current deterministic-first architecture, but makes the review surface easier to inspect and tune.

The goal is not to improve recall at all costs. The goal is to see exactly where recall is lost, where false positives come from, and which knobs are worth touching next.

## Added in v0.7.5

### Reviewer buckets

Every emitted match now includes:

```json
{
  "review_bucket": "duplicate | likely_duplicate | possible_duplicate | needs_review | low_information_ignore",
  "review_priority": "high | medium | low",
  "review_rationale": "plain-English reason"
}
```

These fields are available in:

- `matches[]`
- `candidate_matches[]`
- match CSV
- HTML report
- calibration candidate summary CSV

The buckets are deterministic queue labels, not final adjudication decisions.

### Calibration artifacts

`eval-ab` and `eval-all` now accept optional calibration output flags:

```bash
--calibration-out output/calibration.json
--candidate-summary-csv output/candidate_summary.csv
--false-positive-csv output/false_positive_review.csv
--false-negative-csv output/false_negative_review.csv
--threshold-sweep-csv output/threshold_sweep.csv
--calibration-thresholds 0,0.6,0.74,0.86,0.9,0.94,0.99
```

### Files added

- `src/dupe_engine/review.py`
- `src/dupe_engine/calibration.py`
- `tests/test_review_and_calibration.py`
- `docs/V0_7_5_CALIBRATION.md`

### Files updated

- `src/dupe_engine/models.py`
- `src/dupe_engine/matchers.py`
- `src/dupe_engine/candidates.py`
- `src/dupe_engine/reporting.py`
- `src/dupe_engine/cli.py`
- `README.md`
- `docs/ROADMAP.md`
- `pyproject.toml`
- `src/dupe_engine/__init__.py`

## Validation

Unit tests pass:

```text
27 passed
```

A medium synthetic corpus eval command was also run at `--dpi 72` because the full `150 dpi` render path exceeded the local execution window. That calibration run completed and produced the new v0.7.5 artifacts.

Observed dpi-72 deterministic-only medium run:

```text
Total pages: 375
Matches: 581
True positives: 8
False negatives: 12
Expected negative hits: 9
Partial overlap hits: 0
Low-information ignore hits: 0
Unknown predictions: 564
Recall on must_match: 0.4
```

This is not a final quality claim; it is the first calibration artifact set. The next meaningful work is to inspect the false-negative and false-positive CSVs, then decide whether to tune text top-k/thresholds or enable OCR first.

## Recommended next step

Run the v0.7.5 calibration command against the medium corpus:

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

Then inspect in this order:

1. `synthetic_v2_false_negative_review.csv`
2. `synthetic_v2_false_positive_review.csv`
3. `synthetic_v2_threshold_sweep.csv`
4. `synthetic_v2_candidate_summary.csv`

## Guardrails retained

- OCR remains optional.
- Embeddings remain optional.
- LLM detector/adjudicator remains provisioned but deferred.
- Capability visibility is unchanged.
- The engine still does not delete, merge, or modify source PDFs.
