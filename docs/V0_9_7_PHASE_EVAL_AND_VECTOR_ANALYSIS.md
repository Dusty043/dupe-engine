# v0.9.7 Phase Eval and Vector Analysis Notes

v0.9.7 adds a second evaluation lens next to the old strict truth-pair score.

The old score is still present, but post-OCR and post-embedding runs now need retrieval/evidence metrics too. Use `phase_eval.json` to understand whether the engine is failing because text evidence is still bad, vector retrieval is too broad, or the review queue is overloaded.

Key files emitted when running with `--run-dir` and truth:

```text
truth_eval.json      # strict eval plus embedded phase_eval
phase_eval.json      # standalone phase-aware eval
fallback_audit.json  # OpenAI OCR fallback selection/attempt accounting
fallback_pages.csv   # per-page fallback audit rows
progress.json        # latest run progress
progress_events.jsonl
```

Main sections in `phase_eval.json`:

```text
strict_pair_eval
ocr_rescue_eval
vector_retrieval_eval
review_queue_eval
stage_delta_eval
unknown_prediction_buckets
```

See `docs/V0_9_7_DECISION_LOGIC.md` for the full decision rules.
