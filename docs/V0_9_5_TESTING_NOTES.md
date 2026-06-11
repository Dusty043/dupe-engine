# v0.9.5 Batch Fallback Notes

The medium calibration corpus exposed a selection-policy problem: Tesseract had many weak pages, but OpenAI fallback selected zero pages. v0.9.5 fixes that by adding page-based fallback selection modes.

## Selection modes

| Mode | Behavior |
|---|---|
| `candidate_based` | Old conservative mode: only pages inside strong deterministic candidates. |
| `weak_pages` | Select weak/missing text pages after Tesseract, up to budget. |
| `vision_expected` | Select pages that appear likely to need vision fallback. |
| `weak_pages_or_vision_expected` | Default: candidate pages first, then weak/vision pages up to budget. |

## Recommended calibration config

```bash
export DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
export DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
```

For a more aggressive pass:

```bash
export DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=100
```

For old behavior:

```bash
export DUPE_OPENAI_OCR_SELECTION_MODE=candidate_based
```

## Why low-information pages are allowed by default

After weak OCR, a genuinely text-heavy scanned page can look like an empty or low-information page. v0.9.5 allows those pages into fallback selection by default because the goal is to recover text before candidate generation fails.

To disable that:

```bash
--openai-ocr-exclude-low-info
```

or:

```bash
export DUPE_OPENAI_OCR_ALLOW_LOW_INFORMATION_PAGES=false
```
