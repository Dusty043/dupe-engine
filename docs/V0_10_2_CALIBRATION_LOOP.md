# v0.10.2 Looped Calibration Harness

v0.10.2 adds a looped calibration mode. It does **not** change the duplicate engine, matcher, OCR stack, or adjudicator path. The loop only changes calibration-run configuration and acceptance thresholds.

The loop is for this workflow:

```text
run a calibration batch
-> write scorecard/recommendations/run logs
-> write metrics-only LLM/heuristic analysis
-> generate the next focused config batch
-> stop when worst-case recall reaches the target
```

The default target is:

```text
strict_recall >= 0.80
```

For cross-corpus runs, acceptance uses the worst-case variant recall across corpora. A config that scores high on v3 but fails v4 will not pass.

## What the loop is allowed to change

The loop mutates existing CLI/config knobs only:

```text
OCR cap / per-document OCR cap
OCR reason quotas
embedding profile and vector thresholds
queue profile
main-review acceptance threshold / budget
TF-IDF thresholds
multipass text top-k
sequence-neighbor thresholds
candidate caps
```

It does not add:

```text
new OCR phases
adjudicator calls
LLM candidate detection
new matching algorithms
engine code changes during the run
```

## Dry-run plan

Use dry-run first to inspect the next generated batch:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/generalization_v010 \
  --out-dir ./output/calibration/loop_v0102_plan \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-iterations 2 \
  --dry-run
```

Main dry-run outputs:

```text
calibration_loop_state.json
iteration_01/calibration_manifest.json
iteration_01/scorecard.csv
```

## Live loop

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

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

Remove `--llm-analysis-dry-run` when an OpenAI-compatible analysis model is configured. The analysis payload remains metrics-only by default.

Shortcut script:

```bash
scripts/run_loop_calibration_v0102.sh
```

## Optional acceptance guardrails

Recall is the default stop condition. You can add noise/review-burden limits:

```bash
--accept-max-known-negative-hits 5 \
--accept-max-unknown-predictions 500 \
--accept-max-candidates-per-100-pages 140
```

A variant only passes when it satisfies the recall target and all configured guardrails.

## Iteration artifacts

Each iteration writes:

```text
iteration_NN/calibration_manifest.json
iteration_NN/scorecard.csv
iteration_NN/scorecard.json
iteration_NN/recommended_configs.json
iteration_NN/llm_analysis.md
iteration_NN/llm_analysis.json
iteration_NN/iteration_summary.json
iteration_NN/next_batch_plan.json
iteration_NN/runs/*/command.txt
iteration_NN/runs/*/run_status.json
iteration_NN/runs/*/false_negatives.csv
iteration_NN/runs/*/fallback_audit.json
iteration_NN/runs/*/ocr_validation.json
```

The top-level `calibration_loop_state.json` records the current loop state, acceptance result, and next planned batch.

## Planner behavior

The planner is deterministic so runs are reproducible. The per-iteration LLM analysis is kept as an advisory readout and logged next to the scorecard. The next batch is generated from the scorecard and false-negative reason counts.

Typical mutations:

- `fallback_not_selected` -> raise OCR cap and per-document cap.
- `fallback_selected_but_still_weak` -> keep source-safe evidence enabled and test candidate/sequence thresholds before adding more OCR.
- `deterministic_threshold_or_candidate_generation_miss` -> lower TF-IDF and sequence thresholds, raise text top-k, and raise candidate caps.
- `semantic_or_adjudication_layer_miss` -> widen vector top-k and lower vector thresholds.
- queue misses -> use `recall_first` routing and lower main-review acceptance threshold.

## Regression status

```text
PYTHONPATH=src pytest -q
101 passed
```
