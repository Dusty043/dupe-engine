# v0.8.1 OpenAI Route Governance

## Purpose

v0.8.1 separates **vendor choice** from **engine behavior**.

The product may use one approved OpenAI account/key for compliance, but the engine still needs internal route boundaries so provider calls remain explainable, measurable, and non-redundant.

Bad shape:

```text
call_openai(prompt, files)
```

Good shape:

```text
route = vision_ocr_extraction
route = text_embedding
route = text_adjudication
route = vision_pair_adjudication
```

Each route has its own purpose, input kind, gate, model config, budget, output schema, and audit row.

---

## Route contracts

### `vision_ocr_extraction`

Purpose:

```text
Recover visible page text when native PDF text and Tesseract are weak, and deterministic evidence says the page matters.
```

Input:

```text
single rendered page image
```

Default gate:

```text
native text weak/missing
Tesseract attempted or unavailable
page belongs to a deterministic candidate
candidate confidence meets provider-OCR threshold
page is not low-information
```

This route should not decide whether two pages are duplicates. It should extract visible text only.

---

### `text_embedding`

Purpose:

```text
Compare best available page text semantically after deterministic candidate nomination.
```

Input:

```text
best_text for candidate page pair
```

Default gate:

```text
deterministic candidate exists
candidate is not exact duplicate
candidate is not low-information
both pages have enough usable best_text
```

This route should not create a broad all-pages semantic search by default.

---

### `text_adjudication`

Purpose:

```text
Interpret structured candidate evidence and suggest a reviewer-facing label/explanation.
```

Input:

```text
structured candidate evidence, signals, scores, risk flags, and text snippets only when approved
```

Default gate:

```text
candidate already surfaced
adjudicator policy selects the candidate
human remains final reviewer
```

This route is provisioned but not live in v0.8.1.

---

### `vision_pair_adjudication`

Purpose:

```text
Hard-case visual comparison of two rendered pages when OCR/text/embedding evidence remains inconclusive.
```

Input:

```text
two page images plus structured evidence
```

Default gate:

```text
special escalation only
not part of default v0.8.1 flow
```

This route is intentionally separate from `vision_ocr_extraction` so OCR extraction does not silently become full image-based duplicate judgment.

---

## New outputs

### JSON ledger

```bash
--ai-ledger-out output/ai_ledger.json
```

Contains:

```text
schema_version
summary
route_policies
capabilities
records
```

### CSV ledger

```bash
--ai-ledger-csv output/ai_ledger.csv
```

Important columns:

```text
route
status
provider
model
subject_type
subject_id
input_kind
reason
selected
attempted
succeeded
changed_evidence
changed_matching
dry_run
error
metadata_json
```

No extracted page text is written to the ledger by default.

---

## Status values

Expected route statuses include:

```text
dry_run_skipped
skipped_unavailable
skipped_no_usable_text
completed
error
```

These are intentionally more specific than a generic provider status. They answer whether a route was selected, attempted, completed, skipped, or failed.

---

## Example command

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

This records which pages would have escalated to provider vision OCR without sending page images to the provider.

---

## Why this matters

The desired compliance/audit statement is:

```text
The system does not freely send documents to AI. Each provider call is evidence-gated, route-specific, logged, and tied to a defined review-assist purpose.
```

v0.8.1 gives the codebase the structures needed to support that statement before live embeddings and adjudication are expanded.
