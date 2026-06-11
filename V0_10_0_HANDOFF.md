# Dupe Engine v0.10.0 Handoff

v0.10.0 adds a metrics-only LLM calibration analysis layer on top of the existing calibration harness.

## Why

Calibration runs now produce enough artifacts that reading raw scorecards is slow. The LLM analysis layer gives a concise readout of:

- best config and why
- cross-corpus generalization behavior
- main false-negative bottleneck
- OCR/fallback diagnosis
- vector/embedding diagnosis
- review burden tradeoffs
- next focused experiments
- things not worth retrying yet

It does not run new experiments, change code, or select configs autonomously.

## Primary command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/generalization_v010 \
  --profile generalization \
  --llm-analysis \
  --confirm-live-ai
```

## Analyze an existing calibration

```bash
PYTHONPATH=src python -m dupe_engine.cli analyze-calibration \
  ./output/calibration/generalization_v010
```

Dry-run / heuristic only:

```bash
PYTHONPATH=src python -m dupe_engine.cli analyze-calibration \
  ./output/calibration/generalization_v010 \
  --dry-run
```

## Outputs

```text
llm_analysis.md
llm_analysis.json
```

## Safety

The analysis payload is metrics-only by default. It includes scorecard rows, recommendations, false-negative reason counts, OCR fallback selection counts, queue sizes, and run metadata. It does not include raw OCR text, page images, or PDF contents by default.

An explicit `--llm-analysis-include-text-snippets` / `--include-text-snippets` flag exists for limited false-negative metadata, but it should not be used on real PHI without approval.

## Env

The analysis layer uses OpenAI-compatible chat completions.

Useful env vars:

```text
DUPE_LLM_ANALYSIS_MODEL=gpt-4o-mini
DUPE_LLM_ANALYSIS_BASE_URL=https://api.openai.com/v1
DUPE_LLM_ANALYSIS_API_KEY=...
```

It also falls back to `DUPE_LLM_API_KEY`, `DUPE_OPENAI_API_KEY`, and `OPENAI_API_KEY`.
