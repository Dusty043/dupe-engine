# Dupe Engine v0.8.5 Handoff

## Purpose

v0.8.5 tightens benchmark execution before OCR/embedding calibration.

The main change is practical: make it hard to confuse governance dry-runs with live OCR tests, and make Synthetic v2 medium testing produce both synthetic-metric and production-like outputs.

## Added

### New TUI profile

```text
ocr-live
```

This profile:

```text
enables OCR
enables provider vision OCR fallback
forces OpenAI OCR out of dry-run for this run
leaves embeddings off
```

It is intended for OCR-first provider testing. It should be used only with approved credentials and approved data.

### New provider switch

```bash
--openai-ocr-live
```

This forces `openai_ocr_dry_run=false` for the current run even if the environment has `DUPE_OPENAI_OCR_DRY_RUN=true`.

### New truth control

```bash
--no-truth-autodetect
```

This prevents the engine from using nearby pair-level truth files when `--truth` is omitted.

This is important for production-like benchmark rounds on synthetic corpora, because Synthetic v2 keeps truth files beside the PDFs and would otherwise auto-detect them.

### New paired benchmark mode

```bash
--rounds truth-and-no-truth
```

This writes two benchmark folders:

```text
<output-dir>/with_truth
<output-dir>/no_truth
```

The first round uses explicit or auto-detected truth. The second round disables truth auto-detection and behaves like a production batch.

## Synthetic v2 command

```bash
set -a
source .env
set +a
export DUPE_OPENAI_API_KEY="your_key_here"

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

## Validation in this package

Automated tests:

```text
52 passed
```

The package also includes benchmark smoke outputs. In this sandbox, full Synthetic v2 OCR at 150 DPI did not complete inside the execution window, so the included Synthetic v2 output is a deterministic baseline at 72 DPI to prove paired with-truth/no-truth behavior. Run the 150 DPI `ocr-live` benchmark locally for the real OCR result.

## Notes

- `ocr-live` is not the same as `governance`.
- `governance` intentionally dry-runs OpenAI OCR and embeddings.
- `ocr-live` is the intended profile for OCR-first live provider testing.
- Embeddings remain off in `ocr-live`; use embeddings-specific profiles later.
