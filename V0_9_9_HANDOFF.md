# v0.9.9 Handoff

v0.9.9 is a focused accuracy release built from v0.9.8b.

## Main changes

```text
1. Added post-candidate OpenAI OCR rescue loop.
2. Added experimental hybrid vector scoring profile.
3. Added focused_rescue calibration profile with five runs.
4. Cleaned calibration progress display into multiple progress bars.
5. Added synthetic v4 holdout corpus spec as docs only.
```

## Why

v0.9.8b established the current best profile:

```text
OCR cap: 150
OCR mode: reason_balanced
Vector: conservative
Queue: balanced
```

Remaining false negatives were concentrated around:

```text
fallback_not_selected
fallback_selected_but_still_weak
ocr_or_vision_layer_miss
semantic_or_adjudication_layer_miss
```

So v0.9.9 tests whether a targeted second OCR rescue pass can recover more of those misses without broadening every layer again.

## Run focused calibration

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v099_focused \
  --profile focused_rescue \
  --confirm-live-ai
```

Or:

```bash
scripts/run_medium_calibration_focused_v099.sh
```

## Resume

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v099_focused \
  --profile focused_rescue \
  --resume \
  --skip-existing \
  --confirm-live-ai
```

## New config

```text
DUPE_OPENAI_OCR_POST_CANDIDATE_RESCUE_ENABLED=false
DUPE_OPENAI_OCR_POST_CANDIDATE_MAX_PAGES=0
DUPE_OPENAI_OCR_POST_CANDIDATE_MIN_CONFIDENCE=0.50
DUPE_EMBEDDINGS_HYBRID_SCORING_ENABLED=false
DUPE_EMBEDDINGS_HYBRID_MIN_SCORE=0.78
```

## New docs

```text
docs/V0_9_9_FALLBACK_RESCUE_AND_HYBRID_VECTOR.md
docs/SYNTHETIC_V4_HOLDOUT_SPEC.md
```

## Validation

Expected package validation:

```text
86 tests passed
```
