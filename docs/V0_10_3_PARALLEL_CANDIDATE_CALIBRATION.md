# v0.10.3 Parallel Candidate-Generation Calibration

v0.10.3 changes the next test strategy from broad config search to focused champion/challenger testing.

The goal is still:

```text
strict recall >= 0.80
```

But the working assumption after the 16-hour v0.10.2 loop is:

```text
config-only threshold search has plateaued
```

So v0.10.3 tests a smaller set of candidate-generation changes while keeping runtime safe on a workstation.

## What changed

### 1. Two-run parallel loop cap

`calibrate-loop` now accepts:

```bash
--max-parallel-runs 2
```

The value is capped at `2` internally. If the value is omitted, the loop behaves like the older sequential runner.

When parallel mode is used with the default TUI progress mode, each sub-run writes to its own log and loop progress falls back to plain progress output so multiple dashboards do not fight over the terminal.

### 2. Real LLM analysis by default when not dry-running

The loop still writes metrics-only analysis artifacts after each iteration. To let the LLM actually analyze the run, omit:

```bash
--llm-analysis-dry-run
```

The analysis payload remains metrics-only unless explicitly configured otherwise. It uses the first available key from:

```text
DUPE_LLM_ANALYSIS_API_KEY
DUPE_LLM_API_KEY
DUPE_OPENAI_API_KEY
OPENAI_API_KEY
```

If no key is configured, the analysis artifact records `skipped_no_api_key` and falls back to the heuristic report.

### 3. Candidate-generation challengers

The planner now compares current champion-style runs against deterministic candidate-generation challengers:

```text
champion control
cross-view OCR/native TF-IDF
rare-token/source-token blocking
wider sequence-neighbor promotion
candidate-gen + vector support
```

This is intentionally still pre-adjudicator.

## New candidate-generation passes

### Cross-view text candidates

v0.10.1 compared source views mostly view-to-same-view:

```text
native -> native
Tesseract -> Tesseract
OpenAI OCR -> OpenAI OCR
combined -> combined
```

v0.10.3 adds bounded cross-view comparisons for OCR-relevant pairs such as:

```text
native -> OpenAI OCR
OpenAI OCR -> native
Tesseract -> OpenAI OCR
OpenAI OCR -> Tesseract
primary -> OpenAI OCR
```

This helps cases where one page has usable native text and its duplicate only has useful OCR sidecar text.

Disable it with:

```bash
--disable-cross-view-text-candidates
```

### Rare-token blocking candidates

v0.10.3 also adds a bounded source-safe rare-token pass. It builds uncommon identifier/content tokens from source text views and only scores pairs that share enough rare evidence.

This is not visual all-pairs and not full text all-pairs. It is a blocking pass for cases like:

```text
case IDs
long medication/provider terms
unique appeal/reference tokens
OCR sidecar tokens
```

Useful knobs:

```bash
--rare-token-min-overlap 2
--rare-token-min-jaccard 0.14
--rare-token-max-df 10
```

Disable it with:

```bash
--disable-rare-token-candidates
```

## Safe dry-run plan command

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0102 \
  --out-dir ./output/calibration/loop_v0103_plan \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 2 \
  --dry-run
```

## Live run with real LLM analysis

Do not include `--llm-analysis-dry-run`.

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0102 \
  --out-dir ./output/calibration/loop_v0103 \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 4 \
  --confirm-live-ai
```

Shortcut script:

```bash
scripts/run_loop_calibration_v0103.sh
```

## Reading the result

Look first at:

```text
output/calibration/loop_v0103/calibration_loop_state.json
output/calibration/loop_v0103/iteration_*/scorecard.csv
output/calibration/loop_v0103/iteration_*/llm_analysis.md
output/calibration/loop_v0103/iteration_*/next_batch_plan.json
```

Important checks:

```text
Did cross-view or rare-token candidates increase worst-case recall?
Did unknown_predictions explode?
Did known_negative_hits increase?
Did v3 and v4 diverge further?
Did the LLM recommend a narrower next batch?
```

## Stop condition

Stop broad loops if:

```text
worst-case strict recall does not improve after two iterations
unknown predictions rise without true-positive gain
candidate-generation variants lose to the champion control
```

If that happens, the next work is not more threshold search. It is a deeper engine change or the first controlled adjudication experiment.
