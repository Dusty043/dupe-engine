# v0.9.9b Handoff

v0.9.9b is a cross-corpus calibration release built on v0.9.9a.

## Why this version exists

v3 medium tuning reached a stronger baseline, but v4 calibration showed that the same defaults did not generalize well enough. v0.9.9b changes the calibration question from:

```text
Which config wins this corpus?
```

to:

```text
Which config performs reasonably across v3 and v4?
```

## Main additions

- `generalization` calibration profile.
- Cross-corpus calibration via `--secondary-pdf-dir` and `--secondary-truth`.
- Five config variants run across two corpora, for 10 runs total.
- Experimental OCR evidence upgrade flags.
- Generalization ranking in `recommended_configs.json`.
- Cross-corpus run script: `scripts/run_cross_corpus_generalization_v099b.sh`.

## New command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/generalization_v099b \
  --profile generalization \
  --confirm-live-ai
```

## What to inspect after the run

Open `recommended_configs.json` and inspect:

```text
generalization_summary.best_generalized_config
```

A good config should have:

- strong average recall across corpora,
- stable worst-case recall,
- controlled known-negative hits,
- a reviewable main + secondary queue,
- fewer `fallback_selected_but_still_weak` misses.

## Discussion framing

Calibration is now being used as a generalization check. We are not trying to win one synthetic set. We are choosing settings that keep duplicate discovery reliable across different document batches.
