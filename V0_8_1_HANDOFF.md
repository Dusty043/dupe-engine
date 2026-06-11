# v0.8.1 Handoff: OpenAI Route Governance

v0.8.1 is a governance patch on top of the v0.8 OCR validation harness.

It does **not** add a new AI decision layer. It makes the existing optional OpenAI-compatible routes auditable and clearly separated so one approved OpenAI key does not become one vague all-purpose AI path.

## Why this patch exists

The project may use one approved OpenAI integration for compliance reasons. That is acceptable, but the engine still needs to distinguish:

```text
vision_ocr_extraction
text_embedding
text_adjudication
vision_pair_adjudication
```

These routes have different purposes, input types, gates, budgets, and audit expectations.

## What changed

- Added `src/dupe_engine/ai_ledger.py`.
- Added page/candidate `ai_route_events` metadata.
- Added AI route ledger outputs:
  - `--ai-ledger-out`
  - `--ai-ledger-csv`
- Added `ai_call_summary` to normal JSON reports.
- OpenAI vision OCR fallback now records ledger rows for:
  - dry-run skips
  - unavailable-provider skips
  - live attempts
  - usable/improved results
  - errors
- Embedding route now records ledger rows for:
  - dry-run skips
  - unavailable-provider skips
  - no-usable-text skips
  - provider errors
  - completed comparisons
- Added tests for route ledger behavior.
- Added documentation:
  - `docs/V0_8_1_OPENAI_ROUTE_GOVERNANCE.md`

## Important design boundary

This patch keeps the layer contract narrow:

```text
Tesseract / provider vision OCR = text creation
Embeddings = text comparison
LLM/text adjudicator = evidence interpretation
Vision-pair adjudicator = future hard-case escalation only
```

The engine should not use a generic `call_openai(...)` path for everything.

## Validation

Expected test command:

```bash
PYTHONPATH=src pytest -q
```

Expected smoke command:

```bash
PYTHONPATH=src python -m dupe_engine.cli compare-all \
  examples/synthetic_medical_pdf_corpus/pdfs \
  --work-dir output/v0_8_1_smoke/work \
  --out output/v0_8_1_smoke/results.json \
  --ocr \
  --openai-ocr \
  --openai-ocr-dry-run \
  --ai-ledger-out output/v0_8_1_smoke/ai_ledger.json \
  --ai-ledger-csv output/v0_8_1_smoke/ai_ledger.csv
```

## What this does not solve

- It does not make embeddings calibrated yet.
- It does not enable live adjudication.
- It does not run full vision-pair comparison.
- It does not replace the v0.8 full OCR benchmark requirement.

## Next recommended step

Run the v0.8/v0.8.1 full OCR benchmark locally, then proceed to v0.9 live embeddings calibration using the new AI route ledger as the provider governance report.
