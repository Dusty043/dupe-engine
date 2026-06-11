# v0.8.3 Handoff - Fresh Benchmark Sanity Patch

## Summary

v0.8.3 is a small testing-quality patch created after a clean wipe/fresh test pass of v0.8.2.

It does not change duplicate detection strategy. It fixes benchmark friction and makes bad test inputs fail clearly.

## Why this patch exists

Fresh testing found three practical issues:

```text
1. The bundled corpus has a group-style ground_truth.json that is not pair-level eval truth.
2. The TUI returned success even when its benchmark subprocess failed.
3. 150 DPI OCR testing can be slow with the full multi-profile Tesseract setting.
```

## Changes

- Added explicit setuptools `package-dir` mapping for the `src/` layout.
- Added clear truth-file validation for eval commands.
- Eval commands now validate truth before rendering/comparing PDFs.
- The TUI now exits non-zero when the benchmark subprocess fails.
- Added `--tesseract-profiles` CLI/TUI override.
- Added tests for invalid truth files and TUI command construction.

## Correct bundled example benchmark command

Use the pair-level truth file:

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir examples/synthetic_medical_pdf_corpus/pdfs \
  --truth examples/truth/synthetic_all_pairs_truth.json \
  --output-dir output/benchmarks/v083_example_governance_150dpi
```

Do not use this file for eval benchmarking:

```text
examples/synthetic_medical_pdf_corpus/ground_truth.json
```

That file is corpus/group metadata, not pair-level truth.

## Fresh validation

Automated tests:

```text
43 passed
```

Fresh 150 DPI example governance run with standard Tesseract profile:

```text
pages: 34
matches: 11
true positives: 5
false negatives: 4
recall on must_match: 0.5556
known negative hits: 3
partial overlap hits: 1
raw candidates per 100 pages: 32.3529
main list candidates: 11
Tesseract attempted/usable/improved: 9/8/6
OCR-dependent recall: 0.6667
AI ledger records: 3
provider calls attempted: 0
```

## Next recommended action

Use v0.8.3 for fresh local testing, then run the medium corpus benchmark with the same structure:

```bash
PYTHONPATH=src dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v083_medium_governance_150dpi
```
