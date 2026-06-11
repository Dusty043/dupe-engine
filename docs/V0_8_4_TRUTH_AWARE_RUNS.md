# v0.8.4 Truth-Aware Runs

## Why this exists

The engine should not require a truth file to function. Real production batches will not come with a known answer key. Truth files are for synthetic calibration only.

v0.8.4 makes truth optional and opportunistic.

## Contract

```text
Always run candidate generation.
Always write normal outputs.
Attach evaluation only when valid pair-level truth exists.
```

## Explicit truth behavior

When `--truth` is provided, the engine treats it as strict input.

This should fail:

```bash
dupe-engine eval-all ./pdfs --truth ./missing_truth.json
```

This should also fail:

```bash
dupe-engine eval-all ./pdfs --truth ./metadata_not_pair_truth.json
```

Reason: explicit truth means the user intended an evaluation benchmark. Silent skipping would hide a typo or wrong file.

## Auto-detect behavior

When `--truth` is omitted, the engine checks nearby locations for known pair-level truth filenames:

```text
synthetic_v2_truth_pairs.json
synthetic_all_pairs_truth.json
truth_pairs.json
ground_truth_pairs.json
ground_truth.json
truth.json
```

Candidates are schema-validated before use. Invalid truth-like files are skipped with warnings.

## No-truth behavior

If no valid truth file exists, the run continues.

Expected output state:

```json
{
  "truth_status": {
    "available": false,
    "status": "not_found",
    "source": "auto_detect"
  },
  "evaluation_available": false
}
```

The dashboard displays:

```text
metrics: skipped; no pair-level truth
```

## What still works without truth

No-truth runs still produce:

```text
results.json
matches.csv
review.html
pages.json
ocr_validation.json
ocr_route.csv
ocr_candidate.csv
ai_ledger.json
ai_ledger.csv
calibration.json
candidate_summary.csv
```

The calibration outputs are candidate/reviewability oriented when truth is unavailable. Recall and false-negative metrics remain blank or null.

## What does not exist without truth

Without truth, the engine cannot claim:

```text
recall
false-negative count
known-negative hit rate
OCR-dependent recall
```

Those require known labels.

## Recommended usage

For real batches:

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./real_batch/pdfs \
  --output-dir output/benchmarks/real_batch_governance
```

For synthetic validation:

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v084_medium_governance_150dpi
```
