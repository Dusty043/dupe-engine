# v0.8.6 Handoff — UI-Ready Engine Contract

## Goal

v0.8.6 is a bridge release between the calibrated OCR/vision engine work and the first review UI. It does **not** change the core duplicate detection strategy. It hardens the data contracts that the UI needs.

The main product loop this enables is:

```text
PDF corpus
-> engine run
-> stable run artifact folder
-> review UI reads candidates/pages/assets
-> reviewer saves decisions
-> calibration compares engine/truth/human labels
```

## What changed

### 1. Relative-path document identity

`PageRecord.document_name` now preserves the PDF path relative to the corpus root.

Before:

```text
intake_batch_001.pdf
```

After:

```text
source_A_client_upload/intake_batch_001.pdf
source_B_email_attachment/intake_batch_001.pdf
```

This prevents collisions when different source folders contain files with the same filename.

The original filename is still retained in page metadata:

```json
{
  "relative_pdf_path": "source_A_client_upload/intake_batch_001.pdf",
  "source_pdf_name": "intake_batch_001.pdf"
}
```

### 2. v3 truth file support

The truth loader now accepts both:

```json
{
  "must_match": [],
  "should_not_match": [],
  "partial_overlap": []
}
```

and v3 rich list format:

```json
[
  {
    "pair_id": "v3_pair_000001",
    "left_file": "source_A/intake.pdf",
    "left_page": 1,
    "right_file": "source_B/intake.pdf",
    "right_page": 1,
    "truth_label": "likely_duplicate",
    "expected_min_layer": "ocr",
    "difficulty": "ocr_required",
    "is_must_match": true,
    "reason_tags": ["native_vs_scan"]
  }
]
```

v3 labels are normalized for the existing evaluator:

```text
duplicate / likely_duplicate / possible_duplicate -> duplicate
not_duplicate -> not_duplicate
partial_overlap -> partial_overlap
low_information_ignore -> low_information_ignore
```

The original v3 metadata is retained on `TruthPair`.

### 3. Layer recall breakdown

Evaluation summaries now include:

```json
"recall_by_expected_min_layer": {
  "deterministic": {
    "truth_count": 2,
    "true_positive_count": 2,
    "false_negative_count": 0,
    "recall": 1.0
  },
  "vision_fallback": {
    "truth_count": 1,
    "true_positive_count": 0,
    "false_negative_count": 1,
    "recall": 0.0
  }
}
```

This is the key v3 calibration measure: it shows which layer is earning its keep.

### 4. `--run-dir` UI artifact output

All compare/eval commands now accept:

```bash
dupe-engine eval-all <pdf-dir> --run-dir output/runs/run_001
```

When provided, the engine emits:

```text
run_001/
  run_manifest.json
  pages.json
  candidates.json
  candidate_pairs.json
  capabilities.json
  metrics.json
  truth_eval.json              # eval commands only
  review_decisions.json
  assets/
    page_images/
      *.png
```

The first UI should read this folder directly.

### 5. Review decision placeholder

`review_decisions.json` is created if missing:

```json
{
  "schema_version": "dupe_engine_review_decisions_v0_8_6",
  "decisions": []
}
```

The first UI can update this file without requiring a database.

## Example command

```bash
PYTHONPATH=src dupe-engine eval-all ./examples/synthetic_medical_pdf_corpus/pdfs \
  --truth ./examples/truth/synthetic_all_pairs_truth.json \
  --work-dir ./output/work/ui_smoke \
  --out ./output/ui_smoke/results.json \
  --eval-out ./output/ui_smoke/eval.json \
  --run-dir ./output/ui_smoke/run \
  --dpi 100
```

## Smoke result

A smoke run against the bundled example corpus completed and produced the UI artifact folder.

```text
Total pages: 34
Matches: 10
Truth pairs: 19
Recall on must_match: 0.4444
UI run artifacts: /mnt/data/dupe_086_examples/ui_run
```

A tiny v3 corpus smoke run also verified relative-path matching and v3 truth support.

```text
Documents:
- source_C_scanned_mail/intake_batch_001.pdf
- source_F_fax_batch/intake_batch_001.pdf

recall_by_expected_min_layer:
  deterministic: 1.0
  vision_fallback: 0.0
```

## Tests

```text
55 passed
```

## What this release does not do

v0.8.6 does not implement the review UI yet. It prepares the contract for it.

It also does not implement the full embedding/LLM v2 layer. The schema keeps the slots for those outputs, but the next practical step is the thin local review UI.

## Recommended next step

Build v0.9 UI against the `--run-dir` folder contract:

```text
1. Load run_manifest.json.
2. Show capability status from capabilities.json.
3. Show candidates from candidates.json.
4. Render left/right page images from assets/page_images.
5. Save reviewer labels into review_decisions.json.
```
