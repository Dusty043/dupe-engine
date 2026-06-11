# v0.9.7 Decision Logic

This file documents how the engine decides which pages receive OCR rescue, which vector/embedding neighbors become candidates, how those candidates are labeled for review, and how the new phase-aware evaluation should be interpreted.

The goal of v0.9.7 is **maximum recall with budgeted AI**, without turning OpenAI OCR or embeddings into all-pages/all-pairs brute force.

---

## 1. Overall pipeline

```text
PDF pages
-> native text extraction
-> Tesseract OCR for weak/missing native text
-> budgeted OpenAI OCR rescue for selected weak/vision pages
-> deterministic candidate generation
-> optional embedding/vector analysis
-> candidate aggregation and review gating
-> phase-aware evaluation
-> local review UI
```

LLM candidate detection and adjudication remain v2 provisions. They should not block v1 testing.

---

## 2. OCR rescue decision logic

### OCR is required

v0.9.7 expects OCR and OpenAI OCR fallback to be configured:

```text
DUPE_OCR_ENABLED=true
DUPE_REQUIRE_OCR=true
DUPE_OPENAI_OCR_ENABLED=true
DUPE_REQUIRE_OPENAI_OCR=true
```

This means OpenAI OCR fallback must be available. It does **not** mean every page is sent to OpenAI.

### OpenAI OCR is budgeted

Default budget controls:

```text
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT=5
DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
```

The per-document cap prevents a single noisy bundle from consuming the whole fallback budget.

### Page selection priority

OpenAI OCR rescue can select pages because of:

```text
candidate_based
weak_pages
vision_expected
weak_pages_or_vision_expected
```

In v0.9.7 the intended default is:

```text
weak_pages_or_vision_expected
```

This prevents the failure mode where bad OCR pages never become deterministic candidates and therefore never get fallback.

### Low-information pages

Low-information pages are penalized. They can still be selected if configured, but they should not consume the budget ahead of pages with stronger duplicate potential.

### OpenAI OCR acceptance rule

OpenAI OCR text can replace the current best text when it improves usable evidence.

It should be accepted when it is:

```text
longer and usable
OR
shorter but cleaner and usable
```

It should not be rejected only because the text is shorter than Tesseract output. Forms, notices, and degraded scans often produce shorter but more accurate text.

---

## 3. Deterministic candidate decision logic

The deterministic engine still runs before embeddings and remains the safest source of high-confidence candidates.

Primary deterministic signals:

```text
exact image hash
exact normalized text hash
perceptual image hash
TF-IDF text similarity
```

Deterministic matches are grouped into candidate stages:

```text
deterministic_exact
deterministic_strict
deterministic_standard
deterministic_loose
```

Exact and strong deterministic candidates should always outrank embedding-only candidates in the review queue.

---

## 4. Vector analysis decision logic

v0.9.7 changes embedding recall from simple broad similarity candidate creation into bounded vector-neighborhood analysis.

Bad behavior to avoid:

```text
embed every page
compare every page to every other page
emit every pair above a cosine threshold
```

v0.9.7 behavior:

```text
embed only eligible pages
build nearest-neighbor neighborhoods
score top-k neighbors
measure margin to the next neighbor
measure reciprocal rank
measure source relation
apply gates
emit bounded review candidates
```

### Page eligibility

A page is embedding-eligible only if:

```text
it is not low-information
it has enough post-OCR/native best text
it passes minimum word and character thresholds
```

Default controls:

```text
DUPE_EMBEDDINGS_MIN_WORDS=8
DUPE_EMBEDDINGS_MIN_TEXT_CHARS=120
DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB=1000
```

### Neighbor retrieval

For each eligible page, the engine retrieves up to:

```text
DUPE_EMBEDDINGS_CANDIDATE_TOP_K=5
```

nearest neighbors.

### Vector candidate gates

A vector candidate must pass the configured gates:

```text
similarity >= DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD
margin_to_next >= DUPE_EMBEDDINGS_MIN_MARGIN
OR reciprocal neighbor relationship is strong enough
```

Default:

```text
DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD=0.88
DUPE_EMBEDDINGS_MIN_MARGIN=0.03
DUPE_EMBEDDINGS_MAX_CANDIDATES_PER_PAGE=2
```

Optional stricter gates:

```text
DUPE_EMBEDDINGS_REQUIRE_CROSS_SOURCE=true
DUPE_EMBEDDINGS_REQUIRE_RECIPROCAL=true
```

These are useful when running the real Received-vs-ERE workflow. They may be too strict for all-pairs synthetic corpus experiments that include within-source duplicates.

### Candidate signal details

Each vector-created candidate carries an `embedding_similarity` signal with details like:

```json
{
  "embedding_mode": "vector_recall",
  "vector_analysis": true,
  "query_rank": 1,
  "reciprocal_rank": 2,
  "margin_to_next": 0.061,
  "source_relation": "cross_source",
  "gate": {
    "accepted": true,
    "similarity_ok": true,
    "margin_ok": true,
    "reciprocal_ok": true
  }
}
```

---

## 5. Candidate label and review safety logic

Embedding/vector candidates are retrieval candidates, not final duplicate decisions.

### Safe default

Embedding-only candidates should usually be labeled:

```text
possible_duplicate
needs_review
```

They should not become high-confidence duplicate claims unless supported by additional deterministic, OCR, or visual evidence.

### Strong evidence hierarchy

The engine should trust evidence in this rough order:

```text
exact image/text hash
strong deterministic multi-signal match
OCR/text + visual support
embedding/vector + deterministic support
embedding/vector only
```

### Queue visibility

Low-information and overflow candidates may be suppressed from the main queue but retained in calibration artifacts.

Important distinction:

```text
visibility != label
```

A candidate can be `possible_duplicate` but placed in `calibration_only` if the review queue budget is exceeded.

---

## 6. Phase-aware evaluation logic

v0.9.7 adds phase-aware evaluation because strict pair scoring is not enough after OCR rescue and vector retrieval.

The eval output now includes:

```text
strict_pair_eval
ocr_rescue_eval
vector_retrieval_eval
review_queue_eval
stage_delta_eval
unknown_prediction_buckets
```

### strict_pair_eval

This preserves the old exact truth-pair scoring:

```text
true positives
false negatives
known negative hits
unknown predictions
must-match recall
```

Keep this for regression.

### ocr_rescue_eval

This asks:

```text
Did OCR/fallback make the truth-pair pages usable enough for matching?
```

Important metrics:

```text
native weak/missing pages
Tesseract usable pages
OpenAI selected/attempted/usable/improved pages
truth pairs where both sides became OCR/text usable
truth pairs still OCR-blocked
```

### vector_retrieval_eval

This asks:

```text
Did vector analysis retrieve the right neighborhood?
```

Important metrics:

```text
vector candidate count
embedding-only candidate count
reciprocal vector candidate count
known negative vector hits
recall@1
recall@3
recall@5
average vector margin
average vector similarity
```

Do not treat every vector unknown candidate as a final false positive. Treat it as unjudged retrieval burden unless it hits an explicit `not_duplicate` truth pair.

### review_queue_eval

This asks:

```text
Did the system produce a human-usable queue?
```

Important metrics:

```text
main review candidate count
calibration-only candidate count
must-match coverage in any queue
must-match coverage in main review
known negative hits in main review
unknown candidate burden
```

### stage_delta_eval

This approximates what each stage contributed:

```text
deterministic_without_embedding_signals
embedding_supported_existing_candidates
vector_recall_added_candidates
final_all_candidates
```

Exact pre/post snapshots are not yet persisted, so this is candidate-source attribution, not a full replay of every stage.

---

## 7. Acceptance logic for tuning

A recall improvement is not automatically good. It must be weighed against known-negative hits and review burden.

### OCR rescue pass is good if

```text
must-match recall improves
OCR-dependent recall improves
OpenAI pages stay within budget
selected pages are explainable
known-negative hits do not spike badly
```

### Vector pass is good if

```text
vector recall@k improves
embedding-layer truth pairs are retrieved
candidate count stays reviewable
known-negative vector hits stay controlled
embedding-only unknown candidates are mostly calibration/review-safe
```

### Reject or retune if

```text
unknown vector candidates explode
known-negative hits spike
main review queue becomes too large
embedding-only candidates dominate high-confidence review
OpenAI fallback spends budget on one low-value reason bucket
```

---

## 8. Recommended medium-calibration tuning loop

Run:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
export DUPE_EMBEDDINGS_ENABLED=true
export DUPE_EMBEDDINGS_DRY_RUN=false
scripts/run_medium_accuracy_v097.sh
```

Then inspect:

```text
output/medium_calibration_v3_ocr_vector/eval.json
output/medium_calibration_v3_ocr_vector/phase_eval.json
output/medium_calibration_v3_ocr_vector/fallback_audit.json
output/runs/medium_calibration_v3_ocr_vector/phase_eval.json
```

Tune in this order:

```text
1. OpenAI OCR fallback cap and selection mix
2. embedding similarity threshold
3. embedding margin threshold
4. embedding top-k
5. embedding max candidates per page
6. main review queue visibility budget
```

Do not add LLM adjudication until OCR rescue and vector retrieval are calibrated.
