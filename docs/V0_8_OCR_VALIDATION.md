# v0.8 OCR Validation Notes

v0.8 moves OCR from architecture provision to measurable validation.

## Why this iteration exists

v0.7.6 made output reviewable, but deterministic ranking alone pushed the main review list toward the workload target at the cost of recall. The next suspected failure family is scanned/faxed/rasterized pages. v0.8 therefore asks a narrow question:

```text
Does OCR improve recall enough to justify the runtime and provider complexity?
```

## What changed

### OCR validation artifacts

New optional outputs:

```text
--ocr-validation-out
--ocr-route-csv
--ocr-candidate-csv
```

These are available on `compare-ab`, `compare-all`, `eval-ab`, and `eval-all`.

### Per-page OCR route reporting

Each page now exposes selected/attempted/skipped OCR state:

```text
native_text_status
native_word_count
best_text_source
best_word_count
ocr_route
tesseract_attempted
tesseract_usable
tesseract_confidence
tesseract_profile
openai_ocr_selected
openai_ocr_attempted
openai_ocr_selection_reason
openai_ocr_skip_reason
openai_ocr_error
```

### OpenAI OCR dry-run selection

Before v0.8, OpenAI OCR dry-run mostly showed provider status. v0.8 records selected pages even when calls are disabled. This lets us validate escalation policy without sending page images to a provider.

Dry-run selected pages should show:

```text
openai_ocr_selected=true
openai_ocr_attempted=false
openai_ocr_skip_reason=dry_run
openai_ocr_selection_reason=<candidate-based reason>
```

### OCR-dependent truth recall

When ground truth exists, v0.8 reports:

```text
truth_ocr_dependent_duplicate_count
truth_ocr_dependent_true_positive_count
truth_ocr_dependent_false_negative_count
truth_ocr_dependent_recall
```

A duplicate truth pair is treated as OCR-dependent if its kind/notes mention OCR/scans/fax/image/degraded content, or if either page has weak/missing native text or OCR-derived best text.

## What did not change

v0.8 does not make OpenAI OCR mandatory. It does not enable embeddings by default. It does not change the v1 label contract from v0.7.6.

## Decision logic

```text
1. Native PDF text remains first because it is cheap and deterministic.
2. Tesseract runs only when OCR is enabled and native text is weak/missing.
3. OpenAI OCR fallback is selected only after deterministic candidate evidence exists.
4. Dry-run selection is recorded because provider calls may be blocked by privacy/cost/credentials.
5. OCR outputs are evaluated separately from general candidate calibration so scan-specific failures are visible.
```

## Success criteria for this iteration

v0.8 is good if it can tell us:

```text
which pages need OCR
which pages Tesseract improved
which pages still need fallback OCR
which OCR-dependent truth pairs were recovered
which OCR-dependent truth pairs are still missed
whether OCR increases false positives or candidate load
```

The desired next decision after v0.8 is either:

```text
A. tune OCR further because it clearly helps recall, or
B. move to embeddings/adjudication because OCR is no longer the main blocker.
```
