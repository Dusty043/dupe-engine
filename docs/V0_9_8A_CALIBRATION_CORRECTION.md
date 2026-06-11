# v0.9.8a Calibration Harness Correction

v0.9.8a is a corrective patch for the v0.9.8 calibration harness. The v0.9.8 harness ran successfully, but the first live scorecard showed that the recommendations were not aligned with the project's recall-first goal and that the harness did not include a known-good control run.

## Why this patch exists

The v0.9.8 calibration output was mechanically useful, but it exposed several issues:

- The recommender favored the low-cost/no-AI baseline because the score penalized OpenAI usage and review burden too heavily.
- The harness did not include a v0.9.7-style control run to check whether calibration still reproduced the prior best medium result.
- `reason_balanced` fallback was not counted correctly by fallback eligibility reporting.
- Vector recall was only strict exact-pair recall; the report did not expose truth-group retrieval.
- Scorecard rows lacked enough diagnostic context to understand selected OCR reasons and false-negative causes.

## What changed

### 1. v0.9.7 control run

The default calibration stages now include:

```text
control,ocr,vector,queue
```

The control run uses a v0.9.7-style configuration:

```text
OpenAI OCR cap: 50
OCR selection mode: weak_pages_or_vision_expected
Tesseract profiles: standard
Embedding profile: v097_control
Queue profile: balanced
```

Use this row to verify that the harness can reproduce the last known-good behavior before trusting new staged recommendations.

### 2. Recall-first recommendation scoring

The score now prioritizes recall much more heavily. Costs and queue size still matter, but they should not cause the system to recommend a low-recall baseline when the project goal is to reduce false negatives.

Recommended configs now include:

```text
control_v097
best_by_recall_first_score
best_by_strict_recall
best_by_any_queue_recall
best_reviewable_at_or_above_control
best_low_cost
```

### 3. Reason-balanced fallback accounting fix

Fallback audit eligibility now treats `reason_balanced` as an eligible OCR-rescue policy instead of reporting zero eligible skipped pages.

### 4. Vector group recall

`phase_eval.json` and `scorecard.csv` now include:

```text
vector_group_recall_at_5
```

This credits vector retrieval when it retrieves a page in the same truth group, even if it does not retrieve the exact listed truth pair.

### 5. False-negative reason counts

Each calibration row now includes:

```text
false_negative_reason_counts
```

The per-run `false_negatives.csv` also includes:

```text
pair_id
expected_min_layer
difficulty
reason_tags
reason_missed
```

## Run command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098a \
  --profile balanced \
  --confirm-live-ai
```

Dry-run first:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098a_dry \
  --profile balanced \
  --max-runs 4 \
  --dry-run
```

## How to interpret v0.9.8a output

First check the `control_v097` recommendation. If it does not roughly reproduce the prior v0.9.7 result, investigate harness/config changes before accepting new defaults.

Then compare:

- `best_by_strict_recall`
- `best_by_any_queue_recall`
- `best_reviewable_at_or_above_control`
- `best_by_recall_first_score`

The goal is not the cheapest score. The goal is the highest recall that still creates a reviewable queue.
