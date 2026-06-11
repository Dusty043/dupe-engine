# v0.8.2 Benchmark TUI

## Purpose

v0.8.2 adds a dependency-free terminal UI for benchmark runs and result inspection.

This is not the final Sorter/Organizer product UI. It is a developer/operator aid for the calibration phase so benchmark results are easier to run, compare, and inspect without opening every JSON/CSV file manually.

## Why a TUI now

Before moving to live embedding calibration, the next decision should come from benchmark evidence:

```text
baseline deterministic run
vs
Tesseract OCR run
vs
provider vision-OCR dry-run selection
vs
embedding dry-run governance
```

The TUI keeps those benchmark profiles standardized and prints the same summary every time.

## Command

Interactive menu:

```bash
dupe-engine tui
```

Print a dashboard for an existing benchmark folder:

```bash
dupe-engine tui --summarize output/benchmarks/run_001
```

Print the exact benchmark command without running it:

```bash
dupe-engine tui \
  --print-command \
  --profile governance \
  --dpi 150 \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v082_governance_150dpi
```

Run the benchmark immediately and summarize outputs:

```bash
dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v082_governance_150dpi
```


Optional faster OCR benchmark override:

```bash
dupe-engine tui \
  --run \
  --profile governance \
  --dpi 150 \
  --tesseract-profiles standard \
  --pdf-dir ./synthetic_corpus_v2_medium/pdfs \
  --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json \
  --output-dir output/benchmarks/v082_governance_150dpi
```

## Profiles

| Profile | Purpose | Provider calls |
|---|---|---:|
| `baseline` | Deterministic-only benchmark. Use as a cheap comparison point. | No |
| `ocr` | Native text + Tesseract OCR validation. | No OpenAI calls |
| `ocr-openai-dry-run` | Tesseract plus provider vision-OCR selection reporting. | No |
| `embeddings-dry-run` | OCR plus embedding route selection/governance. | No |
| `governance` | OCR + provider vision-OCR dry-run + embedding dry-run + AI ledger. | No |

The default profile is `ocr`.

## Output folder contents

Every TUI benchmark run writes the major report families:

```text
results.json
matches.csv
review.html
pages.json
eval.json
calibration.json
candidate_summary.csv
false_positive_review.csv
false_negative_review.csv
threshold_sweep.csv
ocr_validation.json
ocr_route.csv
ocr_candidate.csv
ai_ledger.json
ai_ledger.csv
benchmark_command.json
```

`benchmark_command.json` records the exact command used to create the run.

## Dashboard fields

The dashboard summarizes:

```text
pages
matches
OCR pages
text source counts
true positives
false negatives
known negative hits
recall
raw candidates per 100 pages
main review list size
main review list recall
weak/missing native pages
Tesseract attempted/usable/improved
provider vision OCR selected/attempted/usable
OCR-dependent recall
AI route ledger records
AI route dry-runs and route counts
```

## DPI guidance

Use `--dpi 72` for smoke runs only.

Use `--dpi 150` for the benchmark path unless calibration proves a better DPI/runtime tradeoff.

The TUI does not change detector behavior based on DPI. It only passes the chosen DPI to the existing engine command and makes the run easier to inspect.

## Design constraints

The TUI intentionally has no new runtime dependency. It uses only the Python standard library so it is more likely to work on locked-down company machines.

The final v1 UI is still expected to be a proper upload/review web UI with saved decisions and audit history. This TUI is only a calibration/benchmark helper.
