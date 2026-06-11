# v0.9.3 Test Corpora and OCR/OpenAI Configuration

## Summary

v0.9.3 makes the local development loop more realistic for v1 work:

- `small_dev` and `medium_calibration` v3 corpora are bundled under `examples/synthetic_v3/`.
- OCR is enabled and required by default.
- OpenAI is treated as the only external AI provider family.
- One unified OpenAI API key can be used across OCR fallback, embeddings, LLM detector, and adjudicator routes.
- Route-specific key/base URL overrides remain available for cases where a specific capability needs a separate secret or gateway.

## Bundled corpora

```text
examples/synthetic_v3/small_dev
examples/synthetic_v3/medium_calibration
```

The fast corpus is intended for UI and routing smoke tests. The medium corpus is intended for calibration and review-queue pressure testing.

## Run scripts

Fast smoke run:

```bash
scripts/run_small_dev_v3_ocr.sh
```

Medium calibration run:

```bash
scripts/run_medium_calibration_v3_ocr.sh
```

Both scripts write:

```text
output/<corpus>_v3_ocr/results.json
output/<corpus>_v3_ocr/eval.json
output/<corpus>_v3_ocr/ocr_validation.json
output/<corpus>_v3_ocr/ocr_routes.csv
output/<corpus>_v3_ocr/ocr_candidates.csv
output/runs/<corpus>_v3_ocr/
```

Open the review UI on a completed run:

```bash
PYTHONPATH=src dupe-engine review-ui --run-dir output/runs/small_dev_v3_ocr
```

## Mandatory OCR

Default config:

```text
DUPE_OCR_ENABLED=true
DUPE_REQUIRE_OCR=true
```

The browser upload flow also runs jobs with:

```bash
--ocr --require-ocr
```

This prevents the UI from silently producing a non-OCR result on OCR-heavy medical record batches.

## Unified OpenAI key

Preferred:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
```

Also accepted:

```bash
export OPENAI_API_KEY="your_key_here"
```

The unified key is used by default for:

- OpenAI vision OCR fallback
- OpenAI embeddings
- LLM candidate detector provision
- LLM adjudicator provision

## Route-specific overrides

Direct route-specific env vars:

```text
DUPE_OPENAI_OCR_API_KEY
DUPE_EMBEDDINGS_API_KEY
DUPE_LLM_CANDIDATE_API_KEY
DUPE_LLM_API_KEY
DUPE_ADJUDICATOR_API_KEY
```

Named env-var indirection:

```text
DUPE_OPENAI_OCR_API_KEY_ENV
DUPE_EMBEDDINGS_API_KEY_ENV
DUPE_LLM_CANDIDATE_API_KEY_ENV
DUPE_ADJUDICATOR_API_KEY_ENV
```

Resolution priority:

1. Route-specific env-var name from `*_API_KEY_ENV`.
2. Conventional route-specific direct key.
3. Unified env-var name from `DUPE_OPENAI_API_KEY_ENV`.
4. `DUPE_OPENAI_API_KEY`.
5. `OPENAI_API_KEY`.

## Provider policy

v0.9.3 supports the `openai` provider family for external AI routes. Base URLs can still be overridden for approved OpenAI-compatible gateways, but the configured provider value should remain:

```text
openai
```

