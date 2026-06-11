# Dupe Engine v0.9.5.1 Handoff

v0.9.5 is the operational testing patch for the OCR-heavy v1 path.
v0.9.5.1 fixes test isolation, script environment, and dependency declarations found during the first live calibration run (2026-05-30).

## Focus

- Keep OCR and OpenAI OCR fallback as the v1-critical layer.
- Make OpenAI fallback testable without scanning everything.
- Add progress files so medium/large batches do not feel frozen.
- Keep embeddings, LLM candidate detection, and adjudication as non-blocking v2 layers.
- Preserve the existing local Medical Records Sorter Assist UI.

## What changed in 0.9.5.1

### Test fixes (`tests/test_capabilities.py`)

Two tests failed when a real `OPENAI_API_KEY` was present in the shell environment because they did not use `monkeypatch` to clear it. Both now call `monkeypatch.delenv` on `DUPE_EMBEDDINGS_API_KEY`, `DUPE_OPENAI_API_KEY`, and `OPENAI_API_KEY` before building the capability report.

- `test_embedding_status_reports_missing_openai_key`
- `test_required_unavailable_layer_blocks_run`

### Dependency declarations (`pyproject.toml`)

- `openai>=1.0` promoted from optional `[ai]` extra into core `dependencies`. OpenAI OCR is enabled and required by default; it is a real runtime dependency.
- Removed the redundant `ocr` optional extra (`pytesseract>=0.3` was already in core `dependencies`).

### Script fixes (`scripts/run_medium_calibration_v3_ocr.sh`)

| Item | Before | After |
|---|---|---|
| Python interpreter | `python` (system, no pytesseract) | `.venv/bin/python` (resolved from script dir) |
| `OPENAI_OCR_MAX_PAGES` default | 50 | 200 |
| Tesseract min-words | config default (40) | `--tesseract-min-words 20` |

The system Python did not have `pytesseract` installed, so all 567 Tesseract attempts silently returned 0 words and `tesseract_ocr` was reported as unavailable even though Tesseract 5.5.2 is at `/opt/homebrew/bin/tesseract`. Using the venv Python resolves this.

All three values remain overridable via env vars (`PYTHON`, `DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB`, `DUPE_TESSERACT_MIN_WORDS`).

---

## Calibration run findings (2026-05-30)

Full details: `docs/V0_9_5_OCR_CALIBRATION_FINDINGS_2026_05_30.md`

Corpus: `examples/synthetic_v3/medium_calibration` (650 pages, 350 truth pairs)

| Metric | Value |
|---|---|
| Recall (must_match) | 0.3827 |
| True positives | 62 |
| False negatives | 100 |
| OCR-dependent recall | 31/131 = 23.7% |
| Tesseract usable pages | 0/567 |
| OpenAI OCR usable pages | 0/200 |

**Tesseract yields nothing on this corpus.** The synthetic PDF image layers contain no raster text (blank or vector-only). This is confirmed regardless of threshold or venv fix.

**OpenAI OCR blocked by invalid API key.** All 200 calls returned `HTTP 401`. The configured key (`sk-NWNZ8*...`) is expired or wrong. Recall is stuck at 38.3% until a valid key is provided.

---

## Remaining blocker

Supply a valid OpenAI API key:

```bash
export OPENAI_API_KEY="sk-..."
bash scripts/run_medium_calibration_v3_ocr.sh
```

To process all eligible pages (not just the 200 default):

```bash
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=567 bash scripts/run_medium_calibration_v3_ocr.sh
```

---

## New testing artifacts

Engine runs now write progress files when `--progress-dir` is supplied, or when `--run-dir` is supplied:

- `progress.json`
- `progress_events.jsonl`

Runs with `--run-dir` also get fallback audit files:

- `fallback_audit.json`
- `fallback_pages.csv`

These answer:

- Which pages were eligible for fallback?
- Which pages were selected?
- Which pages were attempted?
- Which pages were usable/improved?
- How many eligible pages were not selected because of budget?

## Browser job progress

The local review UI now polls progress from the job run folder and shows:

- current stage
- percentage when available
- recent progress events
- engine failure logs when a job fails

## Fallback budget policy

OpenAI OCR fallback remains mandatory as a configured capability, but calls are capped by policy:

```bash
DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=200
```

## Medium fallback sweep

Use this to compare recall/runtime/call count across budgets:

```bash
export OPENAI_API_KEY="your_key_here"
bash scripts/run_medium_fallback_sweep.sh
```

Default caps:

```text
0 25 50 100
```

Output:

```text
output/fallback_sweep_medium/sweep_summary.csv
```

## Standard medium run

```bash
export OPENAI_API_KEY="your_key_here"
bash scripts/run_medium_calibration_v3_ocr.sh
```

Open UI:

```bash
PYTHONPATH=src .venv/bin/python -m dupe_engine.cli review-ui --run-dir output/runs/medium_calibration_v3_ocr
```

## Validation

```text
72 passed
```

A dry-run smoke run was also checked with OpenAI fallback disabled as a hard requirement:

```bash
DUPE_REQUIRE_OPENAI_OCR=false DUPE_OPENAI_OCR_DRY_RUN=true PYTHONPATH=src .venv/bin/python -m dupe_engine.cli compare-all examples/synthetic_medical_pdf_corpus/pdfs \
  --work-dir output/work/smoke_095 \
  --out output/smoke_095/results.json \
  --run-dir output/runs/smoke_095 \
  --progress-dir output/runs/smoke_095 \
  --ocr --openai-ocr \
  --openai-ocr-max-pages 2 \
  --openai-ocr-selection-mode weak_pages_or_vision_expected \
  --tesseract-profiles standard
```

It produced progress and fallback audit files.
