# v0.8.5 Synthetic v2 Benchmark Rounds

## Why this exists

Synthetic corpora have truth files. Production batches do not.

The engine should support both cases without changing the core run path:

```text
same candidate/OCR/ledger outputs every time
+ evaluation metrics only when truth is available and enabled
```

v0.8.5 adds a paired benchmark mode so Synthetic v2 can be tested in both ways:

```text
with_truth: synthetic calibration view
no_truth: production-like view
```

## New profile: `ocr-live`

Use `ocr-live` for OCR-first provider testing.

It enables:

```text
--ocr
--openai-ocr
--openai-ocr-live
```

It does not enable embeddings.

This keeps the first live provider test focused on OCR only.

## New flag: `--openai-ocr-live`

This flag forces OpenAI OCR fallback out of dry-run mode for the current run.

Use it when:

```text
approved OpenAI/OpenAI-compatible credentials are loaded
OCR provider calls are allowed for the current corpus
you want actual vision OCR extraction attempts, not just route selection
```

Do not use it for governance-only dry-runs.

## New flag: `--no-truth-autodetect`

When `--truth` is omitted, v0.8.4+ can auto-detect nearby truth files.

That is useful for synthetic calibration, but not for production-like simulation. `--no-truth-autodetect` disables that behavior.

Expected no-truth result:

```text
truth status: disabled
metrics: skipped; no pair-level truth
candidate/OCR/ledger artifacts: still generated
```

## New paired mode: `--rounds truth-and-no-truth`

This command:

```bash
dupe-engine tui \
  --run \
  --rounds truth-and-no-truth \
  --profile ocr-live \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v085_v2_ocr_live_150dpi
```

Creates:

```text
output/benchmarks/v085_v2_ocr_live_150dpi/with_truth
output/benchmarks/v085_v2_ocr_live_150dpi/no_truth
```

The `with_truth` round uses the explicit truth file.

The `no_truth` round omits `--truth` and adds `--no-truth-autodetect` internally.

## Recommended OCR-first setup

```bash
python -m pip install -e ".[ocr]"

tesseract --version
python -c "import pytesseract; print(pytesseract.get_tesseract_version())"

set -a
source .env
set +a
export DUPE_OPENAI_API_KEY="your_key_here"

dupe-engine doctor --ocr --openai-ocr --openai-ocr-live
```

Expected live OCR capability shape:

```text
tesseract_ocr: available
openai_ocr_fallback: available
embeddings: disabled
```

## If you only want routing, not provider calls

Use:

```bash
dupe-engine tui \
  --run \
  --rounds truth-and-no-truth \
  --profile ocr-openai-dry-run \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v085_v2_ocr_dry_run_150dpi
```

## Reading the two rounds

Use:

```bash
dupe-engine tui --summarize output/benchmarks/v085_v2_ocr_live_150dpi/with_truth
dupe-engine tui --summarize output/benchmarks/v085_v2_ocr_live_150dpi/no_truth
```

In the `with_truth` dashboard, focus on:

```text
recall on must_match
known negative hits
OCR-dependent recall
main list recall
candidate volume per 100 pages
AI route selected/attempted/succeeded
```

In the `no_truth` dashboard, focus on:

```text
candidate volume per 100 pages
main list candidates
OCR routes
AI ledger records
provider attempts
review.html usability
```

## Sandbox note

The full Synthetic v2 OCR run at 150 DPI can exceed short execution windows because it renders 375 pages and may OCR weak-text pages. Run the real 150 DPI `ocr-live` benchmark locally or in the intended worker environment.
