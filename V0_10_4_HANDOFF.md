# Dupe Engine v0.10.4 Handoff

v0.10.4 is a focused TUI/harness release on top of v0.10.3.

## Goal

Before running another long live calibration loop, keep the two-worker speedup but restore the fancy progress view.

## Main change

v0.10.3 forced this combination to plain output:

```bash
--max-parallel-runs 2 --progress tui
```

v0.10.4 now supports it with a parent-owned aggregate dashboard.

Child sub-runs no longer render dashboards when the loop is running in parallel TUI mode. They write progress artifacts under their run folders, and the parent loop renders one terminal dashboard for the whole iteration.

## Engine impact

No intentional engine behavior change.

The v0.10.3 candidate-generation changes remain available:

```text
cross-view text candidates
bounded rare-token candidates
source-safe OCR evidence views
sequence-neighbor promotion
```

v0.10.4 changes the calibration loop display and tests around it.

## Recommended next run

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
  --out-dir ./output/calibration/loop_v0104 \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 4 \
  --progress tui \
  --confirm-live-ai
```

Important: omit `--llm-analysis-dry-run` when the LLM should actually analyze iteration results.

## Useful checks

```bash
PYTHONPATH=src pytest -q
```

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop --help
```

## Output locations

```text
output/calibration/loop_v0104/calibration_loop_state.json
output/calibration/loop_v0104/iteration_*/scorecard.csv
output/calibration/loop_v0104/iteration_*/scorecard.json
output/calibration/loop_v0104/iteration_*/llm_analysis.md
output/calibration/loop_v0104/iteration_*/next_batch_plan.json
output/calibration/loop_v0104/iteration_*/runs/*/progress.json
output/calibration/loop_v0104/iteration_*/runs/*/progress_events.jsonl
output/calibration/loop_v0104/iteration_*/runs/*/stdout.log
```
