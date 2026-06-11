# v0.10.0 LLM Calibration Analysis

v0.10.0 adds an optional readout layer after calibration.

The flow is:

```text
run calibration matrix
-> write scorecard/recommendations/artifacts
-> compile metrics-only analysis payload
-> optionally call an OpenAI-compatible LLM
-> write llm_analysis.md and llm_analysis.json
```

This is not an autonomous calibration agent. It does not run extra jobs or mutate configs. It only summarizes the artifacts that already exist.

## Metrics included by default

- calibration manifest summary
- scorecard rows
- recommended configs
- generalization summary
- false-negative reason counts
- OpenAI OCR selection reason counts
- OCR fallback selected/attempted/usable/improved counts
- embedding/vector candidate counts
- review queue sizes
- known-negative and unknown-prediction counts
- runtime/status metadata

## Metrics excluded by default

- raw OCR text
- page images
- PDF contents
- full false-negative text previews
- provider raw payloads

## When to use

Use it after long calibration runs when reading the scorecard manually is slowing down the next decision.

Good questions for the report:

- Did this setting generalize across corpora?
- Did recall improve without exploding review burden?
- Is the current bottleneck selection, OCR evidence quality, vector retrieval, or queue routing?
- What should we try next?
- What should we stop retrying?

## Commands

Part of calibration:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate ... --llm-analysis --confirm-live-ai
```

Existing folder:

```bash
PYTHONPATH=src python -m dupe_engine.cli analyze-calibration ./output/calibration/generalization_v010
```
