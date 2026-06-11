# Synthetic v4 Holdout Corpus Spec

## Purpose

`synthetic_v4_holdout` is a validation corpus, not a tuning corpus. It should answer:

```text
Do the v3-calibrated duplicate-checker defaults generalize to a fresh Received-vs-ERE style batch?
```

Do not tune thresholds or defaults repeatedly against this corpus. Run the selected v1 candidate config against it, compare results, and only then decide whether v3 tuning overfit.

## Size

Initial holdout:

```text
250-350 pages
40-70 PDFs
100-180 truth relationships
```

## Directory layout

```text
examples/synthetic_v4_holdout/
  received_records/
    received_batch_001.pdf
    received_batch_002.pdf
  ere_records/
    ere_record_001.pdf
    ere_record_002.pdf
  truth/
    synthetic_v4_truth_pairs.json
    synthetic_v4_truth_summary.json
  corpus_manifest.json
  README.md
```

## Truth labels

Use:

```text
duplicate
likely_duplicate
partial_overlap
same_template_not_duplicate
not_duplicate
low_information_ignore
needs_human_review
```

Each truth pair also needs `expected_min_layer`:

```text
exact_hash
deterministic_text
ocr
openai_ocr
vision_fallback
vector
human_review
llm_adjudication_future
```

`llm_adjudication_future` is allowed as a future-facing label but should not be used to judge v1 readiness.

## Truth schema

```json
{
  "pair_id": "v4_pair_0001",
  "left_file": "received_records/received_batch_001.pdf",
  "left_page": 3,
  "right_file": "ere_records/ere_record_004.pdf",
  "right_page": 8,
  "truth_label": "duplicate",
  "expected_min_layer": "openai_ocr",
  "difficulty": "hard",
  "reason": "Same synthetic medical record page; received version is a low-quality fax scan with stamp artifacts.",
  "tags": ["ocr_heavy", "fax_artifact", "cross_source", "same_patient"]
}
```

Do not include real PHI. Synthetic content only.

## Required distribution

For a roughly 300-page holdout:

### Must-match duplicate / likely duplicate pairs

```text
70-90 pairs
```

Suggested mix:

```text
15 exact/native duplicates
15 near-exact scanned duplicates
15 OCR/OpenAI fallback-required duplicates
10 vector/semantic near-duplicates
10 visual/stamp/watermark duplicates
5 multi-page bundle sequence duplicates
```

### Partial overlaps

```text
20-30 pairs
```

Examples:

```text
same report with one page excerpted
same visit summary with extra appended notes
overlapping medical packet pages
same document with one page missing
```

### Hard negatives

```text
50-80 pairs
```

Required traps:

```text
same template, different patient
same provider, different date
same form, different checkbox values
same document type, different case
similar header/footer only
boilerplate medical instruction pages
```

### Low-information traps

```text
20-40 pages/relationships
```

Examples:

```text
fax cover sheets
blank pages
page with only "continued"
signature-only pages
letterhead-only pages
barcode/stamp-heavy pages
```

## Required document types

Synthetic versions of:

```text
medical visit summaries
lab results
imaging reports
provider letters
therapy notes
medication lists
intake forms
discharge instructions
claim/case cover sheets
fax cover pages
authorization forms
```

## Required transformations

Use combinations of:

```text
scan noise
blur
skew
fax compression
stamp overlay
watermark
cropping
contrast loss
different DPI
native text vs scanned image
OCR corruption
template reuse
added handwritten-like mark
page number changed
date changed
partial redaction
```

## Evaluation protocol

Run the current selected defaults once, then run the next candidate version once.

Track:

```text
strict recall
main_or_secondary recall
OCR-dependent recall
known-negative hits
main queue size
secondary queue size
false-negative reason counts
```

Initial holdout acceptance target:

```text
strict recall:        0.60+
main+secondary recall: 0.65+
OCR-dependent recall: 0.50+
known-negative hits: controlled
queue size: reviewable
```

Stable v1 target remains higher:

```text
strict recall:        0.75-0.80
OCR-dependent recall: 0.65-0.70
```
