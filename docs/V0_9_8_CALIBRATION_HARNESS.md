# v0.9.8 Calibration Harness

v0.9.8 is a recall-calibration release. Its purpose is to stop hand-running one configuration at a time and instead compare OCR fallback, vector recall, and queue-routing settings in one controlled sweep.

## Goal

Find the highest-recall configuration that remains reviewable:

- maximize must-match recall
- improve OCR-dependent recall
- keep OpenAI OCR fallback budgeted
- keep embedding/vector candidates bounded
- separate main review from secondary recall and calibration queues

False positives are treated mostly as review burden. False negatives are treated as the more serious failure because they never reach the reviewer.

## Main command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098 \
  --profile balanced \
  --confirm-live-ai
```

Use `--dry-run` to write the plan without executing engine sub-runs:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098_plan \
  --profile balanced \
  --dry-run
```

## Safety

The harness refuses to execute live AI calls unless `--confirm-live-ai` is present. This is intentional because the matrix can run many OpenAI OCR and embedding calls.

Useful smoke flags:

```bash
--max-runs 2
--dry-run
--resume
--skip-existing
```

## Output

```text
output/calibration/medium_v098/
  calibration_manifest.json
  scorecard.csv
  scorecard.json
  recommended_configs.json
  runs/
    run_001_.../
      results.json
      truth_eval.json
      phase_eval.json
      calibration.json
      false_negatives.csv
      fallback_audit.json
      fallback_pages.csv
      ocr_validation.json
      progress.json
      progress_events.jsonl
      candidate_pairs.json
```

The main artifact is `scorecard.csv`.

## Stages

### Stage A: OCR sweep

Embeddings off. Compare:

- OpenAI fallback caps: `0, 50, 75, 100`
- OCR selection modes: `weak_pages_or_vision_expected`, `reason_balanced`

This identifies whether recall is still blocked by OCR/fallback selection.

### Stage B: Vector sweep

Uses reason-balanced OCR at the profile default cap. Compares:

- `off`
- `conservative`
- `balanced`
- `recall_first`

This measures how much vector recall helps after OCR rescue.

### Stage C: Queue sweep

Uses the profile OCR/vector setting and compares:

- `strict_main`
- `balanced`
- `recall_first`

This decides how candidates should be routed into main review, secondary recall review, and calibration.

## Reason-balanced OpenAI OCR fallback

v0.9.8 adds `reason_balanced` selection so one reason bucket cannot consume the whole fallback budget.

Default quota weights:

```text
vision_expected:30
weak_tesseract:30
no_text:20
candidate_based:20
```

For a 50-page budget, this allocates roughly:

```text
15 vision-expected pages
15 weak-Tesseract pages
10 no-text pages
10 candidate-based pages
```

The fallback audit reports how the budget was actually spent.

## Queue routing

v0.9.8 adds a `secondary_review` visibility bucket.

- `main_review_list`: highest-value reviewer queue
- `secondary_review`: recall-first candidates worth optional review
- `calibration_only`: useful for tuning, hidden from normal review
- `low_information`: low-information pages retained separately

Embedding-only vector candidates are not treated as final duplicate decisions. They usually route to secondary review or calibration unless supported by stronger evidence.

## Scorecard metrics

Important columns:

- `strict_recall`
- `any_queue_recall`
- `main_review_recall`
- `main_or_secondary_recall`
- `ocr_dependent_recall`
- `vector_recall_at_5`
- `known_negative_hits`
- `unknown_predictions`
- `main_queue_size`
- `secondary_queue_size`
- `openai_ocr_attempted`
- `embedding_candidates`
- `reviewable_score`

Pick the highest recall configuration that is still reviewable and affordable.
