# v0.9.2 Handoff — OCR-Mandatory Testing Build

## What changed

v0.9.2 integrates the v3 OCR-heavy test corpora and makes OCR mandatory across engine and UI-created jobs.

Key changes:

- Bundled `examples/synthetic_v3/small_dev`.
- Bundled `examples/synthetic_v3/medium_calibration`.
- Added `scripts/run_small_dev_v3_ocr.sh`.
- Added `scripts/run_medium_calibration_v3_ocr.sh`.
- Changed `EngineConfig` defaults to `enable_ocr=True` and `require_ocr=True`.
- Changed browser-created review UI jobs to always run `--ocr --require-ocr`.
- Removed the browser OCR checkbox and replaced it with an “OCR required” note.
- Added unified OpenAI provider config:
  - `DUPE_OPENAI_API_KEY`
  - `OPENAI_API_KEY`
  - optional route-specific overrides.
- Updated provider/capability status so unsupported external provider values report as unsupported; v0.9.2 expects `openai`.

## Fast local check

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
PYTHONPATH=src pytest -q
PYTHONPATH=src dupe-engine doctor
```

OCR also requires the system Tesseract executable. On macOS:

```bash
brew install tesseract
```

## Run small dev corpus

```bash
scripts/run_small_dev_v3_ocr.sh
PYTHONPATH=src dupe-engine review-ui --run-dir output/runs/small_dev_v3_ocr
```

## Run medium calibration corpus

```bash
scripts/run_medium_calibration_v3_ocr.sh
PYTHONPATH=src dupe-engine review-ui --run-dir output/runs/medium_calibration_v3_ocr
```

## Notes

OpenAI vision fallback remains optional and disabled by default in `.env.example`. Tesseract OCR is the mandatory v1 ingestion reliability layer. The OpenAI key simplification prepares the project for later fallback/embedding/adjudication work without carrying multiple provider abstractions into the v1 config.
