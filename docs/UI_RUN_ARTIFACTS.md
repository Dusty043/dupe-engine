# UI Run Artifact Contract

v0.8.6 introduces `--run-dir`, a stable folder format for the first review UI.

## Command

```bash
dupe-engine eval-all <pdf-dir> --truth <truth-json> --run-dir <run-folder>
```

`--run-dir` is available on:

```text
compare-ab
compare-all
eval-ab
eval-all
```

## Folder layout

```text
run-folder/
  run_manifest.json
  pages.json
  candidates.json
  candidate_pairs.json
  capabilities.json
  metrics.json
  truth_eval.json
  review_decisions.json
  assets/
    page_images/
```

## Primary files

### `run_manifest.json`

Run-level metadata, command, summary counts, truth status, input paths, config snapshot, and artifact names.

### `pages.json`

Page-level records. Each page includes:

```text
page_id
document_name
page_number
asset_image_path
native_text_status
ocr_route
best_text_source
tesseract/openai OCR status fields
low-information fields
```

### `candidates.json`

Reviewer-facing candidate records. Each candidate includes:

```text
candidate_id
rank
queue
confidence
engine_label
review_bucket
review_priority
left/right page refs
signals
escalation
truth metadata when available
review_decision placeholder
```

### `candidate_pairs.json`

A UI-friendly alias of candidate pair records. This exists so future UI code can refer to candidate pairs without relying on older `matches` language.

### `capabilities.json`

Full capability report for deterministic layers, OCR, Tesseract, OpenAI OCR fallback, embeddings, LLM detector, and adjudicator.

### `metrics.json`

Combined run summary:

```text
engine summary
eval summary
calibration summary when requested
OCR summary when requested
AI call summary
```

### `truth_eval.json`

Only emitted for eval commands. Includes the standard truth evaluation plus v3 layer recall breakdown.

### `review_decisions.json`

Initial file:

```json
{
  "schema_version": "dupe_engine_review_decisions_v0_8_6",
  "decisions": []
}
```

Suggested UI decision shape:

```json
{
  "candidate_id": "cand_...",
  "human_label": "duplicate",
  "reviewer_note": "Same page, scan quality differs.",
  "reviewed_at": "2026-05-28T00:00:00Z"
}
```

## Important identity rule

The UI should treat this as the canonical page key:

```text
document_name + page_number
```

`document_name` now preserves relative source path, for example:

```text
source_A_client_upload/intake_batch_001.pdf
```

This avoids collisions across source folders.

## v0.9 local review UI

v0.9 adds a local browser UI that consumes this run folder directly:

```bash
dupe-engine review-ui --run-dir <run-folder>
```

The server exposes the run artifacts through read-only API routes and validates reviewer decision writes to `review_decisions.json`.

Primary routes:

```text
GET  /api/run
GET  /api/review-decisions
POST /api/review-decisions
GET  /run-artifacts/<asset-path>
```

The UI preserves the client-facing workflow language:

```text
Received Medical Records vs ERE Medical Records
```

For `compare-ab` runs, group `A` is displayed as Received Medical Records and group `B` is displayed as ERE Medical Records. All-pairs runs fall back to Left/Right unless the document names include `source_A`, `source_B`, `received`, or `ere`.
