# v0.7 Tiered OCR Design

## Purpose

v0.7 introduces OCR routing that keeps provider use light and justified.

The goal is not to OCR everything with OpenAI. The goal is:

```text
native PDF text first
→ Tesseract for cheap OCR
→ OpenAI OCR only when cheap OCR is weak and the page matters
```

## Page-level route fields

Each `PageRecord` can now report:

```text
native_text_status
tesseract_attempted
tesseract_confidence
tesseract_word_count
tesseract_usable
tesseract_profile
openai_ocr_attempted
openai_ocr_word_count
openai_ocr_usable
ocr_route
ocr_escalation_reason
best_text_source
```

These fields are safe to show in reports because they do not include extracted PHI text unless previews are explicitly enabled.

## Tesseract tier

Tesseract uses TSV-style extraction so the engine can record confidence.

Configured by:

```bash
DUPE_TESSERACT_MIN_CONFIDENCE=65
DUPE_TESSERACT_MIN_WORDS=40
DUPE_TESSERACT_PREPROCESSING_PROFILES=standard,grayscale,high_contrast
```

The engine tries configured preprocessing profiles and keeps the strongest result.

## OpenAI OCR fallback tier

OpenAI OCR fallback is selected after deterministic candidate generation, not at ingest time.

A page can be selected when:

```text
native text is weak or missing
Tesseract was attempted
Tesseract was not usable
candidate confidence is above threshold
candidate is not exact already
page is not low-information
job-level OpenAI OCR budget is not exhausted
```

Configured by:

```bash
DUPE_OPENAI_OCR_ENABLED=true
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
DUPE_OPENAI_OCR_MIN_CANDIDATE_CONFIDENCE=0.60
DUPE_OPENAI_OCR_REQUIRE_TESSERACT_FIRST=true
```

## Why rerun deterministic comparison after OpenAI OCR?

If OpenAI OCR improves a page's `best_text`, the engine recomputes that page's normalized text/hash fields and reruns deterministic comparison. This lets exact text or TF-IDF layers benefit from better OCR before embeddings run.

## Calibration note

v0.7 validates architecture and routing. It does not prove OpenAI OCR accuracy yet because validation outputs were produced without live OpenAI calls.
