# v0.10.5 Handoff — High-Parallel Recall Stress Loop

## Goal

v0.10.5 is a testing-speed and recall-search upgrade on top of v0.10.4.

The immediate goal is not to make the engine production-clean. The goal is to answer:

```text
Can this workstation sustain 10 concurrent calibration sub-runs?
If not, can it sustain 6?
Can an aggressive recall search find a path toward 0.80 strict recall faster?
```

## What changed

### 1. Parallel cap raised

v0.10.4 silently capped `--max-parallel-runs` at `2`.

v0.10.5 allows higher parallelism:

```bash
--max-parallel-runs 10
--parallel-hard-cap 10
```

The default hard cap is `10`. Lower it when the machine is struggling.

### 2. Stress wrapper added

New command:

```bash
dupe-engine calibrate-loop-stress
```

It tries worker counts in order:

```bash
--parallel-candidates 10,6
```

Each trial writes to its own folder:

```text
<out-dir>/p10
<out-dir>/p6
```

A trial is considered throughput-successful if the loop completes with no failed/aborted scorecard rows. It does **not** require hitting 0.80 recall, because this command is about capacity first.

### 3. Compact aggregate TUI

The aggregate parallel TUI now switches to compact mode for larger batches so `10` active/planned runs do not flood the terminal with three-line cards.

### 4. Aggressive recall search

New flag:

```bash
--aggressive-search
```

This adds emergency recall variants that loosen candidate, sequence, rare-token, OCR, embedding, and review thresholds. Expect more unknown predictions. Use this when recall is the top priority and cleanup can happen later.

## Recommended flow

### Step 1 — fast capacity smoke

Run only one iteration first:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate-loop-stress \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0104 \
  --out-dir ./output/calibration/loop_v0105_stress_smoke \
  --target-recall 0.80 \
  --batch-size 5 \
  --max-iterations 1 \
  --parallel-candidates 10,6 \
  --aggressive-search \
  --progress tui \
  --confirm-live-ai
```

### Step 2 — full emergency recall run

Use the selected worker count from `parallel_stress_summary.json`.

If `p10` succeeds, run with `10`. If it fails and `p6` succeeds, run with `6`.

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0104 \
  --out-dir ./output/calibration/loop_v0105_emergency_p10 \
  --target-recall 0.80 \
  --batch-size 5 \
  --max-parallel-runs 10 \
  --parallel-hard-cap 10 \
  --max-iterations 6 \
  --aggressive-search \
  --progress tui \
  --confirm-live-ai
```

Do not include `--llm-analysis-dry-run` if you want live LLM analysis.

## Risk notes

Parallel `10` can overwhelm a Mac through CPU, memory, disk I/O, OCR subprocesses, and OpenAI/API rate limits. The fallback command is designed to discover that quickly and preserve logs.

If the machine becomes unresponsive, stop the run and retry with:

```bash
--max-parallel-runs 6
```

or:

```bash
--parallel-candidates 6,4
```

## Validation

The v0.10.5 patch adds tests for:

```text
high parallel normalization
aggressive recall variant planning
compact aggregate TUI rendering
stress fallback from 10 to 6
```
