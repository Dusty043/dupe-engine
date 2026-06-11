# v0.8.3 Fresh Testing Notes

## Source of truth

This patch started from a clean unpack of `dupe_engine_v0_8_2_project.zip`.

Fresh checks confirmed:

```text
source imports with PYTHONPATH=src
unit/integration tests pass
baseline TUI runs complete
OCR TUI runs complete when Tesseract profile count is constrained
```

## Important truth-file distinction

The example corpus includes two different truth concepts:

```text
examples/synthetic_medical_pdf_corpus/ground_truth.json
```

This is group/corpus metadata. It is useful for understanding the corpus, but it is not pair-level eval truth.

```text
examples/truth/synthetic_all_pairs_truth.json
```

This is the correct pair-level truth file for `eval-all` and TUI benchmark runs.

v0.8.3 now fails early and clearly if a group-style truth file is passed into eval mode.

## Tesseract profiles

Default OCR config still supports multiple profiles:

```text
standard,grayscale,high_contrast
```

For fresh 150 DPI benchmarking on small machines, a faster first run can use:

```bash
--tesseract-profiles standard
```

This does not change the architecture. It only overrides OCR preprocessing profiles for that benchmark run.

## Fresh test command

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

## What the example run showed

```text
Baseline 150 DPI:
  recall: 0.4444
  OCR-dependent recall: 0.3333

OCR/governance 150 DPI with standard Tesseract profile:
  recall: 0.5556
  OCR-dependent recall: 0.6667
```

So OCR is helping on the example corpus, but false positives/template risks still remain.
