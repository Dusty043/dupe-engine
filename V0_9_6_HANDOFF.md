# v0.9.6 Handoff — OCR Rescue + Bounded Embedding Recall

## Purpose

v0.9.6 is the first accuracy-focused patch after the v0.9.5 testability release.

It keeps the v1 product promise intact:

- OCR and OpenAI OCR fallback are required.
- OpenAI fallback is budgeted and does not scan every page by default.
- The UI remains a reviewer-facing tool, not an automated final decision maker.
- LLM adjudication stays disabled and non-blocking.

It adds two recall improvements:

1. Stronger OpenAI OCR rescue acceptance and selection.
2. Optional bounded embedding recall candidate creation.

## Main code changes

### OCR rescue

Touched:

- `src/dupe_engine/config.py`
- `src/dupe_engine/ocr.py`
- `src/dupe_engine/fallback_audit.py`
- `src/dupe_engine/reporting.py`

New/updated config:

```text
DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT=5
DUPE_OPENAI_OCR_LOW_INFORMATION_PENALTY=true
DUPE_OPENAI_OCR_ACCEPT_CLEANER_SHORTER_TEXT=true
```

OpenAI OCR can now improve a page even when the returned text is shorter, as long as it is cleaner and usable. This avoids rejecting clean OCR extracts from forms/notices just because Tesseract produced longer garbage.

Fallback selection now applies a per-document cap after scoring, so one degraded bundle should not consume the full run budget.

### Embedding recall

Touched:

- `src/dupe_engine/embedding_detector.py`
- `src/dupe_engine/engine.py`
- `src/dupe_engine/review.py`
- `src/dupe_engine/matchers.py`
- `src/dupe_engine/capabilities.py`

New/updated config:

```text
DUPE_EMBEDDINGS_MIN_TEXT_CHARS=120
DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB=1000
DUPE_EMBEDDINGS_CREATE_CANDIDATES=true
DUPE_EMBEDDINGS_SKIP_EXACT_MATCHES=true
```

Embeddings are still disabled by default. When enabled, they now do two things:

1. Support/rerank deterministic candidates.
2. Create bounded top-k `embedding_similarity_candidate` pairs from pages with usable post-OCR text.

Embedding-only candidates are reviewer-safe. They are labeled as `possible_duplicate` or `needs_review`, not final duplicates.

## New test coverage

Added:

- `tests/test_096_accuracy.py`

Covers:

- OpenAI OCR can accept shorter but cleaner usable text.
- Fallback selection prioritizes real weak pages over low-information pages.
- Embeddings can create a new candidate pair not found by deterministic matching.
- Existing exact pairs are not duplicated by embedding recall.

Full test result:

```text
76 passed
```

## Key commands

### Medium OCR-only run

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
scripts/run_medium_calibration_v3_ocr.sh
```

### Medium OCR + embedding recall run

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
export DUPE_EMBEDDINGS_ENABLED=true
export DUPE_EMBEDDINGS_DRY_RUN=false
scripts/run_medium_accuracy_v096.sh
```

### Open review UI

```bash
PYTHONPATH=src python -m dupe_engine.cli review-ui \
  --run-dir output/runs/medium_calibration_v3_ocr_embed
```

## What to compare next

Use medium calibration and compare:

```text
Tesseract + OpenAI fallback cap 0
Tesseract + OpenAI fallback cap 25
Tesseract + OpenAI fallback cap 50
Tesseract + OpenAI fallback cap 100
Tesseract + OpenAI fallback cap 50 + embeddings
```

Track:

- must-match recall
- false negatives
- expected negative hits
- candidate count
- main review queue size
- OpenAI OCR pages attempted
- embedding candidates created
- embedding-layer recall

## Still out of scope

- LLM adjudication
- production auth
- multi-reviewer workflow
- database-backed review decisions
- all-pages/all-pairs brute-force embeddings
- automatic deletion/removal of records
