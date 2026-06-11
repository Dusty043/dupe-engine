# v0.9.5 OCR Calibration Run — Findings (2026-05-30)

Corpus: `examples/synthetic_v3/medium_calibration`
Script: `scripts/run_medium_calibration_v3_ocr.sh`
Two consecutive runs: first with original script, second after fixes applied this session.

---

## Test Suite

72 tests collected across 18 test files. Prior to this session 2 tests were failing in `tests/test_capabilities.py`.

### Failures fixed

Both failures were in `test_capabilities.py` and shared the same root cause: the tests assumed no `OPENAI_API_KEY` was set in the environment but did not use `monkeypatch` to enforce that. When a real key exists in the shell environment, `check_embeddings_status` resolves it and reports the layer as `available`, causing assertions to fail.

| Test | Assertion | Root cause |
|---|---|---|
| `test_embedding_status_reports_missing_openai_key` | `status.available is False` | Live env had `OPENAI_API_KEY` set |
| `test_required_unavailable_layer_blocks_run` | `report.blocking_errors` non-empty | Same — embeddings became available, no blocking errors |

Fix: added `monkeypatch.delenv` for `DUPE_EMBEDDINGS_API_KEY`, `DUPE_OPENAI_API_KEY`, and `OPENAI_API_KEY` to both tests, matching the pattern already used by `test_ocr_and_openai_fallback_are_enabled_and_required_by_default`.

**Result: 72/72 passing.**

---

## Run 1 — Original script (before fixes)

```
Total pages: 650
Tesseract attempted/usable: 567/0
OpenAI OCR selected/attempted/usable: 50/50/0
Recall (must_match): 0.3827
OCR-dependent duplicate recall: 31/131 = 0.2366
tesseract_ocr capability: unavailable (pytesseract Python package is not installed)
```

### Issues identified

**1. Script used bare `python`, not the venv**

`PYTHONPATH=src python -m dupe_engine.cli ...` resolves to the system Python, which does not have `pytesseract` installed. The venv at `.venv/` does have it. This caused `check_tesseract_ocr_status` to report `unavailable` with reason "pytesseract Python package is not installed", even though Tesseract 5.5.2 is present at `/opt/homebrew/bin/tesseract`.

**2. OpenAI OCR budget too low**

Default of 50 pages left 517 eligible pages unprocessed (budget skip). With the `weak_pages_or_vision_expected` selection mode, many pages that need vision OCR were never attempted.

**3. OpenAI OCR usable=0 — invalid API key**

All 50 OpenAI OCR calls returned `HTTP 401 Incorrect API key`. The key configured in the environment (`sk-NWNZ8*...`) is invalid/expired. This is the primary reason recall did not improve despite OCR being invoked.

**4. `tesseract_min_words` threshold too high for corpus**

Default is 40 words. The corpus pages with weak native text have 31–39 words. Even if Tesseract extracted the same word count from the image, all results would be rejected by the threshold.

**5. `openai>=1.0` was optional-only**

The `ai` optional extra held `openai>=1.0` but it was not in core `dependencies`. Since OpenAI OCR is enabled and required by default in v0.9.5, this is a real runtime dependency.

---

## Changes applied

### `pyproject.toml`

- Promoted `openai>=1.0` from optional `[ai]` extra into core `dependencies`.
- Removed the redundant `ocr` optional extra (`pytesseract>=0.3` was already in core `dependencies`; the extra just created confusion).

```toml
# Before
dependencies = [
  "pymupdf>=1.23", "pillow>=10", "scikit-learn>=1.3", "numpy>=1.24", "pytesseract>=0.3",
]
[project.optional-dependencies]
ocr = ["pytesseract>=0.3"]
ai  = ["openai>=1.0"]
dev = ["pytest>=8"]

# After
dependencies = [
  "pymupdf>=1.23", "pillow>=10", "scikit-learn>=1.3", "numpy>=1.24",
  "pytesseract>=0.3", "openai>=1.0",
]
[project.optional-dependencies]
dev = ["pytest>=8"]
```

### `scripts/run_medium_calibration_v3_ocr.sh`

| Change | Before | After |
|---|---|---|
| Python interpreter | `python` (system) | `.venv/bin/python` (resolved from script dir) |
| `OPENAI_OCR_MAX_PAGES` default | `50` | `200` |
| `TESSERACT_MIN_WORDS` default | _(not passed, config default 40)_ | `20` via `--tesseract-min-words` |

All three values remain overridable via env vars (`PYTHON`, `DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB`, `DUPE_TESSERACT_MIN_WORDS`).

---

## Run 2 — After fixes

```
Total pages: 650
Tesseract attempted/usable: 567/0
OpenAI OCR selected/attempted/usable: 200/200/0
Recall (must_match): 0.3827
OCR-dependent duplicate recall: 31/131 = 0.2366
tesseract_ocr capability: available ✓
```

### What improved

- `tesseract_ocr` now reports **available** — the venv fix worked.
- OpenAI OCR processed **200 pages** vs 50, now including 149 `vision_expected` pages that were skipped before.
- `--tesseract-min-words 20` is active.

### What did not improve

- **Tesseract usable still 0.** 567 pages attempted, 0 words extracted from any. The synthetic corpus pages that have `native_text_status=weak` do have some PDF text layer (31–39 words), but the raster image layer appears to contain no scannable text (blank or vector-only). Tesseract cannot help this corpus regardless of threshold.
- **OpenAI OCR usable still 0.** All 200 calls returned `HTTP 401` — the same invalid API key. Recall unchanged at 38.3%.
- **OCR-dependent recall: 31/131 = 23.7%.** 131 truth pairs depend on OCR to be detected. None of the 200 OpenAI pages improved text enough to lift any of those pairs into a match.

---

## Remaining blocker

The **invalid OpenAI API key** is the only remaining blocker for improving recall on this corpus. Tesseract is confirmed non-viable for this synthetic data (image layers have no raster text).

To unblock:

```bash
export OPENAI_API_KEY=sk-...   # valid key
bash scripts/run_medium_calibration_v3_ocr.sh
```

Expected impact once a valid key is used:
- OpenAI vision OCR should produce usable text for the 200 selected pages
- OCR-dependent duplicate recall (currently 23.7%) should rise
- Overall recall (currently 38.3%) should improve toward the theoretical ceiling for this selection mode

To increase coverage further, raise the budget to cover all 567 eligible pages:

```bash
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=567 bash scripts/run_medium_calibration_v3_ocr.sh
```

---

## Summary table

| Item | Status |
|---|---|
| Test suite (72 tests) | All passing ✓ |
| `test_capabilities` monkeypatch fix | Applied ✓ |
| `pytesseract` in core deps | Confirmed ✓ |
| `openai` in core deps | Promoted ✓ |
| Script uses venv Python | Fixed ✓ |
| Tesseract capability detected | Fixed ✓ |
| OpenAI OCR budget | Raised 50→200 ✓ |
| Tesseract min-words threshold | Lowered 40→20 ✓ |
| Tesseract usable pages | Still 0 (corpus has no raster text) |
| OpenAI OCR usable pages | Still 0 (invalid API key) |
| Recall | 0.3827 (blocked by invalid key) |
