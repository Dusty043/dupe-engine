# v0.9.9a Handoff

v0.9.9a is a calibration/operator release built on v0.9.9.

## Purpose

This release adds the fresh `synthetic_v4_calibration` corpus and a focused five-run v4 calibration profile. It also improves the calibration terminal display so long live runs are easier to monitor.

## Current baseline to beat

From v0.9.8b on synthetic v3 medium calibration:

```text
strict recall:        0.6235
true positives:       101
false negatives:      61
OCR-dependent recall: 0.5344
known negatives:      1
unknown predictions:  206
```

v0.9.9 did not beat this baseline. v0.9.9a is intended to test the current model on the new v4 calibration corpus rather than continuing to overfit v3.

## New profile

```text
--profile v4_calibration
```

The profile runs five tests:

```text
1. cap150 + conservative vector + balanced queue + rescue0
2. cap225 + conservative vector + balanced queue + rescue0
3. cap150 + conservative vector + balanced queue + rescue50
4. cap225 + conservative vector + balanced queue + rescue25
5. cap225 + balanced vector + balanced queue + rescue0
```

The point is to answer:

```text
Does the current best v3 profile transfer to v4?
Does a higher first-pass OCR cap help on v4?
Does targeted rescue help on v4?
Does v4 need broader vector retrieval?
```

## Run command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v4_calibration \
  --truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --out-dir ./output/calibration/v4_v099a \
  --profile v4_calibration \
  --confirm-live-ai
```

Or:

```bash
scripts/run_v4_calibration_v099a.sh
```

## TUI changes

The calibration TUI now shows:

```text
- overall calibration progress
- current run progress
- PDF/Tesseract progress
- OpenAI OCR fallback progress
- candidate generation progress
- vector progress
- post-candidate rescue progress
- artifact/report progress
- last completed run summaries
```

Use plain logs if the terminal dashboard is not desired:

```bash
--progress plain
```

## v4 corpus

Packaged at:

```text
examples/synthetic_v4_calibration/
```

Truth file:

```text
examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json
```

## Validation notes

v4 calibration is a tuning corpus, not the holdout. The holdout should remain untouched until a candidate v1 default is selected.
