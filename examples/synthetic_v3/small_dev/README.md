# Synthetic Corpus v3 - Small dev corpus

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
  "profile_name": "small_dev",
  "profile_label": "Small dev corpus",
  "generated_at_unix": 1779931026,
  "seed": 13001,
  "pdf_file_count": 18,
  "page_count": 100,
  "target_pages": 100,
  "truth_group_count": 28,
  "truth_pair_count": 53,
  "document_truth_count": 3,
  "must_match_pair_count": 33,
  "hard_negative_pair_count": 18,
  "ocr_or_weak_native_page_count": 66,
  "ocr_or_weak_native_page_percent": 66.0,
  "vision_fallback_expected_page_count": 20,
  "text_layer_type_counts": {
    "image_only_blurry": 3,
    "image_only_clean_scan": 17,
    "image_only_fax_quality": 7,
    "image_only_low_contrast": 2,
    "image_only_low_quality_scan": 22,
    "image_only_skewed": 1,
    "image_only_stamp_or_watermark": 5,
    "mixed_native_and_scanned": 8,
    "native_text_clean": 34,
    "native_text_poor_extraction": 1
  },
  "expected_ocr_quality_counts": {
    "corrupted": 15,
    "good": 17,
    "minimal": 2,
    "native_clean": 34,
    "partial": 31,
    "weak_native": 1
  },
  "truth_label_counts": {
    "duplicate": 18,
    "likely_duplicate": 7,
    "not_duplicate": 20,
    "partial_overlap": 6,
    "possible_duplicate": 2
  },
  "expected_min_layer_pair_counts": {
    "deterministic": 10,
    "embedding": 10,
    "human_review": 5,
    "llm_adjudication": 11,
    "ocr": 13,
    "vision_fallback": 4
  },
  "difficulty_counts": {
    "adjudication_required": 4,
    "easy": 8,
    "hard_negative": 18,
    "ocr_corrupted": 2,
    "ocr_required": 11,
    "partial_overlap": 2,
    "semantic_required": 4,
    "vision_required": 4
  },
  "source_group_page_counts": {
    "source_A_client_upload": 13,
    "source_B_email_attachment": 26,
    "source_C_scanned_mail": 11,
    "source_D_legacy_export": 23,
    "source_E_manual_rescan": 13,
    "source_F_fax_batch": 14
  },
  "document_family_page_counts": {
    "appeal_letter": 3,
    "benefit_determination_letter": 4,
    "case_cover_sheet": 5,
    "checkbox_form": 6,
    "email_printout": 5,
    "evidence_bundle": 22,
    "fax_correspondence": 4,
    "hearing_notice": 11,
    "id_information_page": 1,
    "medical_appointment_note": 2,
    "medical_summary": 12,
    "receipt_proof_of_payment": 8,
    "signature_form": 8,
    "tribunal_order": 9
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
python generate_synthetic_corpus_v3.py --profile small_dev --out ./regenerated_small_dev
```
