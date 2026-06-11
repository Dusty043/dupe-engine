# Calibration Plan

Calibration is intentionally after architecture stability.

v0.6 provides the pieces calibration needs:

- deterministic pass history
- low-information suppression
- candidate budget controls
- embedding support signal
- capability reporting
- v2 truth bucket parsing

## Calibration sequence

1. Deterministic only.
2. Deterministic + low-information suppression.
3. Deterministic + candidate budgets.
4. Deterministic + OCR.
5. Deterministic + OCR + embeddings.
6. Borderline candidates + LLM detector/adjudicator.

## Metrics

Track:

```text
must-match recall
known negative hit rate
low-information hit rate
candidate count per 100 pages
candidates per page
embedding support count
false positives by category
false negatives by category
```

In production there is no ground truth, so reviewer feedback becomes the calibration source.
