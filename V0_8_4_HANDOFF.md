# v0.8.4 Handoff - Truth-Aware Runs

## Goal

Make the benchmark/TUI path behave more like production:

```text
Run the engine every time.
Use pair-level truth only when it is explicitly provided or safely auto-detected.
Do not require truth for normal candidate/OCR/ledger/report generation.
```

Production jobs will not have an answer key. Synthetic validation jobs may.

## What changed

- `eval-all` and `eval-ab` now accept optional `--truth`.
- Explicit `--truth` remains strict:
  - missing file fails clearly
  - invalid pair-level schema fails clearly
- When `--truth` is omitted, the engine attempts nearby truth auto-detection.
- If no valid truth is found, the run continues and writes normal outputs.
- `eval.json` is still written, but marks `evaluation_available: false`.
- `results.json`, `calibration.json`, and `ocr_validation.json` include `truth_status`.
- TUI `--run` no longer requires `--truth`.
- Dashboard shows whether metrics were truth-backed or skipped.

## New behavior

### Production-like run

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./some_real_batch/pdfs \
  --output-dir output/benchmarks/prod_like_run
```

Expected behavior:

```text
Engine runs.
Candidates are produced.
OCR route reports are produced.
AI ledger is produced.
Evaluation metrics are skipped if no truth exists.
```

### Synthetic run with explicit truth

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir examples/synthetic_medical_pdf_corpus/pdfs \
  --truth examples/truth/synthetic_all_pairs_truth.json \
  --output-dir output/benchmarks/v084_example_governance_150dpi
```

Expected behavior:

```text
Engine runs.
Evaluation metrics are attached.
Calibration and OCR truth metrics are populated.
```

### Synthetic run with auto-detected truth

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir examples/synthetic_medical_pdf_corpus/pdfs \
  --output-dir output/benchmarks/v084_example_auto_truth_150dpi
```

Expected behavior:

```text
Engine looks near the PDF folder for a valid pair-level truth file.
If found, metrics are attached.
If not found, run continues without metrics.
```

## Validation

```text
47 passed
```

Smoke outputs were generated for:

- explicit truth benchmark
- auto-detected truth benchmark
- no-truth production-like benchmark

## Important note

No-truth runs are not accuracy benchmarks. They are production-like candidate-generation runs. They can tell us candidate volume, OCR activity, visibility distribution, and AI route usage, but they cannot honestly tell us recall or false-negative rate.
