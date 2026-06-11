# Handoff: Dupe Engine v0.4

## Intent

v0.4 implements deterministic multi-pass candidate generation so the engine can lower thresholds before escalating to AI.

The goal is:

```text
Do not miss likely duplicates because one strict threshold was too high.
Do not use embeddings/LLM until cheaper deterministic passes justify it.
```

## New concept

Every candidate can now include:

```text
candidate_stage
deterministic_passes
escalation
```

Example:

```json
{
  "candidate_stage": "deterministic_loose",
  "deterministic_passes": [
    {"pass_name": "strict_visual", "matched": false},
    {"pass_name": "standard_visual", "matched": false},
    {"pass_name": "loose_visual", "matched": true}
  ],
  "escalation": {
    "embedding_required": true,
    "llm_detector_required": false,
    "reason": "deterministic candidate is not exact; embedding support is justified before stronger AI use"
  }
}
```

## Default bands

```text
Visual pHash distance:
strict   <= 8
standard <= 16
loose    <= 28

TF-IDF cosine similarity:
strict   >= 0.94
standard >= 0.86
loose    >= 0.74
```

## New CLI options

```bash
--single-threshold
--strict-phash-threshold
--standard-phash-threshold
--loose-phash-threshold
--strict-tfidf-threshold
--standard-tfidf-threshold
--loose-tfidf-threshold
--multipass-text-top-k
```

## Validation performed

```bash
PYTHONPATH=src python -m pytest -q
```

Result:

```text
13 passed
```

Synthetic all-pairs evaluation:

```bash
PYTHONPATH=src python -m dupe_engine.cli eval-all ./examples/synthetic_medical_pdf_corpus/pdfs \
  --truth ./examples/truth/synthetic_all_pairs_truth.json \
  --out output/all_pairs_eval_results.json \
  --eval-out output/all_pairs_eval.json \
  --html output/all_pairs_eval_report.html \
  --embeddings \
  --llm
```

Result:

```text
Total pages: 34
Predicted candidates: 93
True positives: 9
False negatives: 0
Expected negative hits: 6
Partial overlap hits: 4
Unknown predictions: 74
Recall on must_match: 1.0000
```

## Important interpretation

v0.4 is not more precise yet. It is more recall-oriented.

The larger candidate count is intentional. It shows that lowered deterministic bands are catching all current must-match pairs, but calibration is still needed to reduce false positives and unknown predictions.

## Next step

Do not jump straight to LLM adjudication.

Next best build:

```text
OpenAI embedding detector
→ only for candidates with embedding_required=true
→ with max pairs per job
→ compare before/after embedding support
```
