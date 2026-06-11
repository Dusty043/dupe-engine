# v0.10.1 Source-Safe Multiview Candidate Generation

v0.10.1 changes how evidence is used after extraction. The engine now keeps OpenAI OCR as sidecar evidence and generates candidates from multiple text views instead of depending on one final canonical text field.

## Source-safe OCR merge

When `source_safe_ocr_merge_enabled` is true, accepted OpenAI OCR is retained in the OpenAI OCR fields and summarized in `page.meta["source_safe_ocr_merge"]`. It does not overwrite the canonical native/Tesseract-derived page text.

This prevents weaker OpenAI OCR from degrading pages that already had strong native or Tesseract evidence, while still letting the matcher use OpenAI OCR as an independent candidate source.

## Text views used for candidates

The matcher can generate text candidates from these views:

```text
primary_text       canonical comparison/raw/best text
native_text        extracted PDF text
tesseract_text     local OCR text
openai_ocr_text    OpenAI OCR sidecar text
combined_text      deduplicated combination of source texts
```

Signals are named by source, for example:

```text
tfidf_cosine_similarity
tfidf_native_text_similarity
tfidf_tesseract_text_similarity
tfidf_openai_ocr_text_similarity
tfidf_combined_text_similarity
```

Exact source-view hashes can emit:

```text
exact_source_text_hash
```

## Key-token candidates

The matcher also extracts a small set of source-safe key tokens from source evidence, such as dates, claim/case identifiers, MRNs, and high-value labels. These can emit:

```text
key_token_overlap
```

The key-token path stores counts and overlap metadata in candidate records, not raw full source text.

## Sequence-neighbor promotion

A strong anchor match can promote nearby page pairs. For example, if page 4 in one group strongly matches page 9 in another, the engine can check page 5 against page 10 and page 3 against page 8.

Promotion is bounded by:

```text
sequence_neighbor_window
sequence_anchor_min_confidence
sequence_min_text_similarity
sequence_min_text_similarity_with_visual
sequence_visual_support_phash_threshold
```

Promoted candidates emit:

```text
sequence_neighbor_promotion
```

## Bounded visual use

The visual pass remains bounded. It still avoids full visual all-pairs unless `--multipass-visual-all-pages` is explicitly used. v0.10.1 additionally allows OCR-weak pages into the bounded visual pass so layout/visual evidence can help candidate formation when text is weak.

## Diagnostics

OCR validation reports now include:

```text
summary.openai_ocr_sidecar_evidence_pages
summary.source_safe_candidate_ready_pages
summary.ocr_ready_but_not_candidate_generated_count
ocr_ready_missed_candidate_rows
```

Fallback audit reports now include sidecar evidence counts and per-page sidecar availability.

## Safety note

The multiview matcher builds source views on demand and does not persist a second full-text PHI path in page metadata. Diagnostics expose counts, sources, signal names, and matching metadata rather than full source-view text.
