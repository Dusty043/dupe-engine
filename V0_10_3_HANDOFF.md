# Dupe Engine v0.10.3 Handoff

## Summary

v0.10.3 adds focused candidate-generation improvements and updates the calibration loop so long runs can execute two engine tests concurrently on a workstation.

This release is based on the v0.10.2 loop evidence: broad config/threshold search plateaued well below `.80` strict recall, and the best configs were still bootstrap/champion-style runs. The next test should compare the champion against deterministic candidate-generation challengers rather than running another broad 16-hour matrix.

## Engine changes

### Cross-view text candidate generation

The multiview text matcher can now compare OCR/native views against each other, not only same-view pairs.

Examples:

```text
native_text -> openai_ocr_text
tesseract_text -> openai_ocr_text
primary_text -> openai_ocr_text
```

This targets pages where duplicate evidence exists but lands in different extraction sources on each side.

Disable with:

```bash
--disable-cross-view-text-candidates
```

### Rare-token candidate generation

Added a bounded rare-token/source-token blocking pass. It indexes uncommon long or identifier-like tokens across source-safe text views and emits candidates only when a pair shares enough rare evidence.

Useful config knobs:

```bash
--rare-token-min-overlap 2
--rare-token-min-jaccard 0.14
--rare-token-max-df 10
```

Disable with:

```bash
--disable-rare-token-candidates
```

## Harness changes

### Parallel calibration loop

`calibrate-loop` now supports:

```bash
--max-parallel-runs 2
```

The value is capped at `2` internally. Sequential behavior remains available by omitting the flag.

### Real LLM analysis

The loop already runs per-iteration analysis. To use real LLM analysis, do not pass `--llm-analysis-dry-run` and provide an API key through one of the supported environment variables.

The default analysis remains metrics-only and does not include OCR/document text snippets.

## Recommended live command

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

## What to compare

1. `seed_v0102_champion_control`
2. `seed_cross_view_candidate_recall`
3. `seed_rare_token_candidate_recall`
4. `seed_sequence_crossview_wide`
5. `seed_vector_candidate_support`

The key question is whether candidate-generation variants improve worst-case strict recall without exploding unknown predictions or known-negative hits.

## Validation

Core targeted validation added:

```text
cross-view native/OpenAI OCR candidate generation
rare-token blocking candidate generation
calibrate-loop dry-run state with max_parallel_runs
bootstrap loop planning includes candidate-generation challengers
```

Run:

```bash
PYTHONPATH=src pytest -q
```
