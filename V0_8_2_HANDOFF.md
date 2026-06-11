# v0.8.2 Handoff - Benchmark TUI

## Summary

v0.8.2 adds a dependency-free terminal UI for running and inspecting benchmark profiles before the project moves into live embeddings calibration.

This release does not change detection thresholds or add new AI behavior. It standardizes benchmark commands and makes existing output artifacts easier to inspect.

## New command

```bash
dupe-engine tui
```

Useful non-interactive forms:

```bash
dupe-engine tui --summarize output/benchmarks/run_001
```

```bash
dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v082_governance_150dpi
```

## Benchmark profiles

```text
baseline
ocr
ocr-openai-dry-run
embeddings-dry-run
governance
```

`governance` is the safest comprehensive benchmark preset for now because it enables OCR, provider vision-OCR dry-run selection, embedding dry-run route records, and the AI ledger without making provider calls.

## Added files

```text
src/dupe_engine/tui.py
tests/test_tui.py
docs/V0_8_2_BENCHMARK_TUI.md
V0_8_2_HANDOFF.md
```

## Validation

Automated tests:

```text
40 passed
```

Smoke TUI run on the bundled synthetic example corpus:

```text
profile: governance
DPI: 72
pages: 34
matches: 10
OCR pages: 1
Tesseract attempted/usable/improved: 9/3/1
provider vision OCR selected/attempted/usable: 0/0/0
AI route ledger records: 2
provider calls attempted: 0
recall on must_match: 0.4444
main review list candidates per 100 pages: 29.4118
OCR-dependent recall: 0.3333
```

The smoke run used `--dpi 72` only to validate the TUI path quickly. It is not the full OCR benchmark.

## Next recommended action

Run the medium corpus benchmark locally at `--dpi 150` using the TUI governance profile:

```bash
dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v082_medium_governance_150dpi
```

Then compare that result against a baseline profile run:

```bash
dupe-engine tui \
  --run \
  --profile baseline \
  --dpi 150 \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v082_medium_baseline_150dpi
```
