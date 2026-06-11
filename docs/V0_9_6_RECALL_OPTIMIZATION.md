# v0.9.6 Recall Optimization Notes

v0.9.6 implements the accuracy plan around OCR rescue and bounded embedding recall.

## OCR rescue rules

OpenAI OCR fallback is required as a configured capability, but calls are budgeted.

Selection priorities:

1. Weak pages inside useful candidates.
2. Pages explicitly marked `vision_fallback_expected`.
3. Weak/missing text pages after Tesseract.
4. Low-information pages only when allowed, and penalized by default.

Budget controls:

```text
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT=5
DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
```

Acceptance rules:

- Accept OpenAI OCR when it returns longer usable text.
- Also accept shorter text when it is cleaner and usable.
- Reject unusable text and record the acceptance/skip reason in the page metadata/audit files.

## Embedding recall rules

Embeddings are disabled by default and are non-blocking unless explicitly required.

When enabled:

```text
DUPE_EMBEDDINGS_ENABLED=true
DUPE_EMBEDDINGS_DRY_RUN=false
DUPE_EMBEDDINGS_MODEL=text-embedding-3-small
DUPE_EMBEDDINGS_CANDIDATE_TOP_K=10
DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD=0.88
DUPE_EMBEDDINGS_MIN_TEXT_CHARS=120
DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB=1000
DUPE_EMBEDDINGS_CREATE_CANDIDATES=true
DUPE_EMBEDDINGS_SKIP_EXACT_MATCHES=true
```

The embedding detector only embeds pages with enough usable post-OCR text. It creates top-k semantic candidates and sends them through the same review/artifact path as deterministic candidates.

Embedding-only candidates remain reviewer-facing candidates. They should be treated as `possible_duplicate` or `needs_review`, not final duplicate decisions.

## Recommended benchmark comparison

Run:

```bash
scripts/run_medium_fallback_sweep.sh
scripts/run_medium_accuracy_v096.sh
```

Then compare:

- recall on must-match pairs
- false negatives by expected layer
- known negative hits
- candidate count per 100 pages
- main review queue size
- OpenAI fallback selected/attempted/usable/improved pages
- embedding candidate count
- embedding route AI ledger entries
