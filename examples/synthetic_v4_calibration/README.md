# synthetic_v4_calibration

Synthetic v4 calibration corpus for duplicate-detection tuning.

This corpus is intentionally shaped as a received-records vs ERE-records workflow:

```text
received_records/
ere_records/
truth/
```

It is designed to determine whether the current v3/v0.9.x ceiling is an engine ceiling or an eval/corpus ceiling.
It should be used for tuning. Do not tune against the holdout profile.

## Summary

```json
{
  "corpus_id": "synthetic_v4_calibration",
  "description": "Fresh tuning corpus for pushing recall beyond the v3 calibration ceiling.",
  "document_truth_count": 13,
  "ere_pdf_count": 28,
  "expected_min_layer_counts_truth_pairs": {
    "deterministic": 46,
    "embedding": 12,
    "group_level_sequence": 12,
    "llm_adjudication": 30,
    "openai_ocr": 29,
    "vision_fallback": 17
  },
  "expected_ocr_quality_counts": {
    "corrupted": 30,
    "good": 76,
    "low_information_native": 24,
    "low_information_scan": 16,
    "minimal": 19,
    "native_clean": 125,
    "partial": 113,
    "weak_native": 17
  },
  "expected_risk_layer_counts_negative_pairs": {
    "human_review": 25,
    "llm_adjudication": 45
  },
  "failure_category_counts_all_relationships": {
    "fallback_not_selected": 9,
    "fallback_selected_but_still_weak": 13,
    "low_information_suppressed": 25,
    "ocr_or_vision_layer_miss": 24,
    "partial_overlap_needs_review": 42,
    "same_template_hard_negative": 45,
    "semantic_or_adjudication_layer_miss": 12
  },
  "generated_at_unix": 1780501438,
  "hard_negative_pair_count": 70,
  "low_information_negative_pair_count": 25,
  "low_information_trap_page_count": 40,
  "negative_pair_count": 70,
  "page_count": 420,
  "partial_overlap_pair_count": 30,
  "pdf_count": 60,
  "positive_must_or_likely_pair_count": 116,
  "profile": "calibration",
  "received_pdf_count": 32,
  "same_template_negative_pair_count": 45,
  "seed": 44040,
  "source_root_counts": {
    "ere_records": 203,
    "received_records": 217
  },
  "target_pages": 420,
  "text_layer_counts": {
    "image_only_blurry": 2,
    "image_only_clean_scan": 76,
    "image_only_fax_quality": 21,
    "image_only_low_contrast": 11,
    "image_only_low_quality_scan": 65,
    "image_only_partial_crop": 4,
    "image_only_photo_angle": 4,
    "image_only_stamp_or_watermark": 7,
    "low_information_native": 24,
    "low_information_scan": 16,
    "mixed_native_and_scanned": 48,
    "native_text_clean": 125,
    "native_text_poor_extraction": 17
  },
  "top_document_family_counts": {
    "appeal_statement": 5,
    "benefit_determination_letter": 37,
    "case_cover_sheet": 4,
    "checkbox_form": 21,
    "employer_letter": 24,
    "evidence_bundle": 122,
    "fax_correspondence": 6,
    "hearing_notice": 34,
    "id_information_page": 13,
    "low_information_blank_separator": 8,
    "low_information_ere_barcode_cover": 4,
    "low_information_fax_transmission_receipt": 9,
    "low_information_one_line_index": 5,
    "low_information_page_number_only": 8,
    "low_information_signature_only": 5,
    "medical_summary": 29,
    "medical_visit_note": 32,
    "receipt_proof_of_payment": 9,
    "signature_statement": 8,
    "tribunal_order": 27
  },
  "truth_group_count": 73,
  "truth_pair_count": 146,
  "truth_relationship_count": 216,
  "vision_fallback_expected_page_count": 34,
  "weak_or_ocr_page_count": 295,
  "weak_or_ocr_page_pct": 0.7024
}
```

## Truth files

- `truth/synthetic_v4_calibration_pages.json`: page-level metadata, OCR/scan quality, low-information flags, fallback hints.
- `truth/synthetic_v4_calibration_truth_pairs.json`: positive duplicate, likely duplicate, and partial-overlap page pairs.
- `truth/synthetic_v4_calibration_truth_groups.json`: group-level truth for document-neighborhood recall and adjacent-page credit.
- `truth/synthetic_v4_calibration_negative_pairs.json`: hard negatives and low-information traps.
- `truth/synthetic_v4_calibration_truth_documents.json`: document-level sequence/partial-overlap relationships.
- `truth/synthetic_v4_calibration_all_relationships.json`: convenience union of truth_pairs and negative_pairs.

## Important eval distinction

Strict page-pair eval answers:

```text
Did the engine return this exact pair?
```

Group-level eval answers:

```text
Did the engine find the right duplicate neighborhood or acceptable adjacent page?
```

Use both. A system can find the correct received/ERE neighborhood but miss an exact page offset, and v4 is designed to expose that distinction.

## Failure categories

The corpus marks the current miss buckets directly:

```text
fallback_not_selected
fallback_selected_but_still_weak
ocr_or_vision_layer_miss
semantic_or_adjudication_layer_miss
low_information_suppressed
same_template_hard_negative
partial_overlap_needs_review
```

## Recommended workflow

1. Freeze the v0.9.8b best run as baseline.
2. Treat v0.9.9 rescue/hybrid as experimental.
3. Run both against this calibration corpus.
4. Review false negatives by `failure_category` and `expected_min_layer`.
5. Tune on calibration only.
6. Generate the holdout profile later with a separate command and do not tune against it.

## Fake data notice

All names, case numbers, addresses, providers, employers, record IDs, and dates are generated fake data.
