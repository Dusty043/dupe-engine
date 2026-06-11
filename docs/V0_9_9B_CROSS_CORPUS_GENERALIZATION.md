# v0.9.9b Cross-Corpus Generalization Calibration

## Goal

v0.9.9b evaluates whether candidate v1 settings generalize across both:

```text
synthetic_v3/medium_calibration
synthetic_v4_calibration
```

The key output is not just the best single run. It is the best config variant across corpora.

## Profile

Use:

```bash
--profile generalization
```

The profile runs five variants on each corpus:

1. `stable_baseline` — cap150, conservative vector, balanced queue.
2. `evidence_conservative` — baseline plus OCR evidence upgrade.
3. `evidence_balanced_vector` — OCR evidence upgrade plus balanced vector.
4. `evidence_recall_queue` — OCR evidence upgrade plus recall-first queue routing.
5. `evidence_high_dpi` — OCR evidence upgrade plus balanced vector at 200 DPI.

## OCR evidence upgrade

The OCR evidence upgrade is experimental. It enables:

- key-token acceptance for short OCR outputs,
- combined native + Tesseract + OpenAI text evidence,
- metadata-only OCR quality signals for calibration.

It is intended to test the current bottleneck: pages selected for OpenAI OCR that still do not become useful matching evidence.

## Ranking

`recommended_configs.json` includes:

```text
generalization_summary.variants
generalization_summary.best_generalized_config
```

The score rewards average recall, worst-case recall, any-queue recall, and OCR-dependent recall, while penalizing known negatives, review burden, unknown predictions, and OpenAI call volume.

## How to explain this

A one-corpus winner can be misleading. A production duplicate checker needs settings that work across different document batches. v0.9.9b treats calibration as a stability test: the selected config should perform well on v3 and not collapse on v4.
