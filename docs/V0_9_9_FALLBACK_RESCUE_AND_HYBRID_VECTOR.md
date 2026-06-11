# v0.9.9 Fallback Rescue and Hybrid Vector Test

v0.9.9 is a focused accuracy pass built on the v0.9.8b baseline.

The current best v0.9.8b profile is:

```text
OCR cap: 150
OCR mode: reason_balanced
Vector: conservative
Queue: balanced
```

v0.9.9 does not rerun the broad calibration matrix by default. It tests one focused hypothesis:

```text
Can a targeted second-pass OpenAI OCR rescue loop recover more false negatives after deterministic/vector candidates exist?
```

## New pieces

### 1. Post-candidate OpenAI OCR rescue

The first OpenAI OCR fallback pass remains quota-balanced and page-quality based. The new optional second pass runs after deterministic and vector candidates exist. It spends a separate reserve budget only on remaining weak pages attached to suspicious candidates.

Relevant config:

```text
DUPE_OPENAI_OCR_POST_CANDIDATE_RESCUE_ENABLED=false
DUPE_OPENAI_OCR_POST_CANDIDATE_MAX_PAGES=0
DUPE_OPENAI_OCR_POST_CANDIDATE_MIN_CONFIDENCE=0.50
```

CLI flags:

```bash
--openai-ocr-post-candidate-rescue
--openai-ocr-post-candidate-rescue-pages 50
--openai-ocr-post-candidate-min-confidence 0.50
```

### 2. Hybrid vector scoring test profile

Hybrid vector scoring is experimental and opt-in. It does not replace the existing conservative vector profile.

It combines:

```text
embedding similarity
neighbor rank
margin to next neighbor
reciprocal rank
text quality
OCR text source
visual support
low-information penalty
source relation penalty
```

CLI flags:

```bash
--embedding-hybrid-scoring
--embedding-hybrid-min-score 0.78
```

Calibration profile:

```text
hybrid_test
```

### 3. Cleaner calibration progress dashboard

The calibration display now shows multiple progress bars:

```text
Overall runs
Current stage
PDF/Tesseract OCR
OpenAI OCR
Post-candidate rescue
Vector embeddings
Reports/artifacts
```

Use `--progress plain` for log-friendly output or `--progress none` for quiet mode.

## Focused calibration command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v099_focused \
  --profile focused_rescue \
  --confirm-live-ai
```

Convenience wrapper:

```bash
scripts/run_medium_calibration_focused_v099.sh
```

## Focused run set

The focused matrix has five runs:

```text
1. cap150 + conservative vector + no second-pass rescue
2. cap150 + conservative vector + rescue25
3. cap150 + conservative vector + rescue50
4. cap150 + hybrid_test vector + rescue50
5. cap150 + hybrid_test vector + rescue75
```

This is intentionally smaller than the v0.9.8b accuracy matrix. Use the broad matrix only when changing a major layer.

## What success looks like

Compare to the v0.9.8b best baseline:

```text
strict recall:        0.6235
OCR-dependent recall: 0.5344
known negative hits:  1
unknown predictions:  206
main queue:           163
secondary queue:      150
```

A useful v0.9.9 result should improve recall and OCR-dependent recall without exploding known negatives or secondary queue size.

Target:

```text
strict recall:        0.65+
OCR-dependent recall: 0.56+
known negative hits:  controlled
main+secondary queue: reviewable
```
