# Handoff: Dupe Engine v0.7

## Summary

v0.7 adds tiered OCR routing:

```text
native PDF text
→ Tesseract TSV/confidence
→ selected OpenAI OCR fallback
→ rerun deterministic comparison if OCR improves text
```

This follows the project principle: cheap layers first, provider calls only when justified.

## What was implemented

- `EngineConfig` OCR fields for native/Tesseract/OpenAI OCR tiers.
- Tesseract TSV provider with confidence and preprocessing profiles.
- OpenAI-compatible OCR fallback provider.
- OCR route metadata on `PageRecord`.
- OpenAI OCR page selection after deterministic candidates exist.
- Rerun of deterministic comparison after OpenAI OCR improves pages.
- Capability reporting for:
  - `ocr`
  - `tesseract_ocr`
  - `openai_ocr_fallback`
- CLI flags:
  - `--ocr`
  - `--openai-ocr`
  - `--openai-ocr-dry-run`
  - `--tesseract-min-confidence`
  - `--tesseract-min-words`
  - `--native-min-usable-words`
  - `--openai-ocr-max-pages`
  - `--openai-ocr-min-candidate-confidence`

## Validation performed

```bash
PYTHONPATH=src python -m pytest -q
```

Result:

```text
23 passed
```

Synthetic v2 deterministic baseline remained aligned with v0.6:

```text
Pages: 375
Candidates: 627
True positives: 10 / 20
False negatives: 10
Known negative hits: 11
Low-information-ignore hits: 0 / 50
```

Small OCR smoke test:

```text
Pages: 34
Tesseract attempted: 9
Tesseract usable: 0
OpenAI OCR attempted: 0
```

OpenAI OCR dry-run verified capability visibility without provider calls.

## Important note

No live OpenAI OCR calls were made during validation. v0.7 is the routing/provider foundation. Accuracy gains from OCR need calibration runs using approved credentials and controlled inputs.
