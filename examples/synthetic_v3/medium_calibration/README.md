# Synthetic Corpus v3 - Medium calibration corpus

This directory contains a generated OCR-heavy synthetic PDF corpus for duplicate, near-duplicate, OCR, vision fallback, embedding, and adjudication evaluation.

All names, addresses, case numbers, providers, employers, identifiers, emails, and dates are fake. The PDFs are intentionally synthetic and must not be treated as real case records.

## Contents

- `source_*/*.pdf` - synthetic incoming files grouped by source batch.
- `synthetic_v3_pages.json` - page-level metadata for every page.
- `synthetic_v3_truth_pairs.json` - pair-level truth labels and expected minimum engine layer.
- `synthetic_v3_truth_groups.json` - truth groups used to create duplicate/near-duplicate clusters.
- `synthetic_v3_truth_documents.json` - document-level partial-overlap truth.
- `synthetic_v3_benchmark_modes.json` - comparable v1/v2 mode definitions.
- `synthetic_v3_evaluation_metrics.json` - metric definitions this corpus is designed to support.
- `synthetic_v3_summary.json` - generated counts and acceptance checks.
- `synthetic_v3_generation_config.json` - generation profile, seed, source groups, and type lists.

## Summary

```json
{
  "profile_name": "medium_calibration",
  "profile_label": "Medium calibration corpus",
  "generated_at_unix": 1779931048,
  "seed": 23001,
  "pdf_file_count": 63,
  "page_count": 650,
  "target_pages": 650,
  "truth_group_count": 150,
  "truth_pair_count": 350,
  "document_truth_count": 15,
  "must_match_pair_count": 192,
  "hard_negative_pair_count": 150,
  "ocr_or_weak_native_page_count": 491,
  "ocr_or_weak_native_page_percent": 75.54,
  "vision_fallback_expected_page_count": 136,
  "text_layer_type_counts": {
    "image_only_blurry": 14,
    "image_only_clean_scan": 170,
    "image_only_fax_quality": 46,
    "image_only_low_contrast": 21,
    "image_only_low_quality_scan": 121,
    "image_only_partial_crop": 14,
    "image_only_skewed": 20,
    "image_only_stamp_or_watermark": 23,
    "mixed_native_and_scanned": 50,
    "native_text_clean": 159,
    "native_text_poor_extraction": 12
  },
  "expected_ocr_quality_counts": {
    "corrupted": 83,
    "good": 170,
    "minimal": 35,
    "native_clean": 159,
    "partial": 191,
    "weak_native": 12
  },
  "truth_label_counts": {
    "duplicate": 110,
    "likely_duplicate": 37,
    "needs_review": 10,
    "not_duplicate": 158,
    "partial_overlap": 30,
    "possible_duplicate": 5
  },
  "expected_min_layer_pair_counts": {
    "deterministic": 58,
    "embedding": 62,
    "human_review": 60,
    "llm_adjudication": 73,
    "ocr": 75,
    "vision_fallback": 22
  },
  "difficulty_counts": {
    "adjudication_required": 23,
    "easy": 58,
    "hard_negative": 150,
    "ocr_corrupted": 7,
    "ocr_required": 68,
    "semantic_required": 22,
    "vision_required": 22
  },
  "source_group_page_counts": {
    "source_A_client_upload": 105,
    "source_B_email_attachment": 111,
    "source_C_scanned_mail": 117,
    "source_D_legacy_export": 103,
    "source_E_manual_rescan": 91,
    "source_F_fax_batch": 123
  },
  "document_family_page_counts": {
    "appeal_letter": 24,
    "benefit_determination_letter": 68,
    "case_cover_sheet": 29,
    "checkbox_form": 39,
    "email_printout": 27,
    "employer_letter": 26,
    "evidence_bundle": 119,
    "evidence_packet_cover": 35,
    "fax_correspondence": 19,
    "hearing_notice": 65,
    "id_information_page": 10,
    "medical_appointment_note": 44,
    "medical_summary": 53,
    "receipt_proof_of_payment": 34,
    "signature_form": 22,
    "tribunal_order": 36
  }
}
```

## Intended use

Run the same candidate-generation pipeline against this corpus in these modes:

1. deterministic only
2. deterministic + OCR
3. deterministic + OCR + vision fallback dry-run
4. deterministic + OCR + vision fallback live
5. deterministic + OCR + embeddings
6. deterministic + OCR + embeddings + LLM adjudication

The key report should include recall by `expected_min_layer`, queue size, hard-negative false-positive rate, and partial-overlap detection rate.

## Important truth fields

Each truth pair has:

- `truth_label`: one of `duplicate`, `likely_duplicate`, `possible_duplicate`, `partial_overlap`, `not_duplicate`, `needs_review`.
- `expected_min_layer`: one of `deterministic`, `ocr`, `vision_fallback`, `embedding`, `llm_adjudication`, `human_review`.
- `difficulty`: scenario-level difficulty such as `ocr_required`, `vision_required`, `semantic_required`, `adjudication_required`, `hard_negative`, or `partial_overlap`.
- `is_must_match`: whether recall should count the pair as a required match.
- `is_hard_negative`: whether the pair is a false-positive trap.
- `expected_mode_behavior`: expected retrieval behavior by benchmark mode.

## Regeneration

Use the bundled generator from the parent package:

```bash
python generate_synthetic_corpus_v3.py --profile medium_calibration --out ./regenerated_medium_calibration
```
