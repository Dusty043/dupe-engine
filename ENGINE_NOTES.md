# Engine Notes v0.7

## Current goal

v0.7 adds **tiered OCR routing** without changing the overall product strategy:

1. Keep deterministic multi-pass as the cheap high-recall layer.
2. Suppress low-information noise before AI escalation.
3. Use Tesseract first for cheap worker-side OCR.
4. Use OpenAI OCR fallback only for selected high-value pages where cheap OCR is weak.
5. Keep embeddings and LLM/adjudication downstream.

## v0.7 changes

- Added native text status:
  - `usable`
  - `weak`
  - `missing`
- Added Tesseract TSV/confidence route.
- Added Tesseract preprocessing profiles.
- Added Tesseract usability fields:
  - `tesseract_attempted`
  - `tesseract_confidence`
  - `tesseract_word_count`
  - `tesseract_usable`
  - `tesseract_profile`
- Added OpenAI-compatible OCR fallback provider.
- Added OpenAI OCR selection policy after deterministic candidates exist.
- Added OCR route fields:
  - `ocr_route`
  - `ocr_escalation_reason`
  - `best_text_source`
- Added OCR route counts to summary reports.
- Added `openai_ocr_fallback` capability visibility.

## Tiered OCR route

```text
native PDF text
→ if usable, no OCR
→ if weak/missing, Tesseract OCR
→ if Tesseract usable, use Tesseract text
→ if Tesseract weak and candidate evidence justifies it, OpenAI OCR fallback
→ if OpenAI OCR improves text, rerun deterministic comparison
```

## Still deferred

- Live OpenAI OCR calibration.
- Cloud OCR comparison against Tesseract.
- Embeddings after OCR on Synthetic v2.
- LLM candidate detector.
- LLM adjudicator agent.
- Calibration against reviewer feedback.

## Design rule

Use the cheapest useful layer first.

```text
native text
→ Tesseract
→ OpenAI OCR fallback
→ embeddings
→ LLM detector/adjudicator
```

Every escalation should have a recorded reason.


## v0.7.5 calibration note

v0.7.5 adds reviewer buckets and optional eval-time calibration artifacts. This version is intended to make false positives, false negatives, and threshold tradeoffs inspectable before turning on broader OCR, embeddings, or adjudicator behavior.
