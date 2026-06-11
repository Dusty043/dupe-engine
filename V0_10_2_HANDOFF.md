# Dupe Engine v0.10.2 Handoff

v0.10.2 keeps the v0.10.1 engine intact and improves the calibration harness.

## Purpose

The next calibration move is a looped test harness that can keep proposing focused config batches until a target recall threshold is reached.

Default target:

```text
strict_recall >= 0.80
```

For cross-corpus runs, the loop evaluates worst-case recall across corpora, not only the best single score.

## Main changes

1. Added `calibrate-loop` CLI command.
   - Runs iterative calibration batches.
   - Stops when the target recall and optional guardrails pass.
   - Requires `--confirm-live-ai` for live execution.
   - Supports `--dry-run` for first-batch planning.

2. Added deterministic metrics planner.
   - Reads scorecards and false-negative reason counts.
   - Writes a next-batch plan after each iteration.
   - Mutates only existing config/threshold knobs.

3. Added per-iteration LLM/heuristic analysis.
   - Each iteration can write `llm_analysis.md` and `llm_analysis.json`.
   - Payload is metrics-only by default.
   - Analysis is advisory; the generated batch remains deterministic and reproducible.

4. Added richer scorecard config columns.
   - TF-IDF thresholds
   - candidate caps
   - main-review acceptance settings
   - sequence-neighbor thresholds
   - OCR per-document cap
   - vector candidate limits

5. Added loop documentation and regression coverage.

## Key command

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/generalization_v010 \
  --out-dir ./output/calibration/loop_v0102 \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-iterations 4 \
  --llm-analysis-dry-run \
  --confirm-live-ai
```

Shortcut script:

```bash
scripts/run_loop_calibration_v0102.sh
```

## Safety boundaries

This version intentionally does not add adjudication or any new engine detection logic. The loop only changes run configuration and thresholds already exposed by the CLI/config layer.

## Validation

```text
PYTHONPATH=src pytest -q
101 passed
```

Also checked the new CLI help and a dry-run loop seeded from the existing `generalization_v010` calibration artifacts.
