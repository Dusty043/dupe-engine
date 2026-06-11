# Iteration Decision Log

This document records the process and decisions behind each iteration so the project does not lose context between calibration passes.

## Guiding product decision

The Duplicate Checker is a human-review assist tool. The system should surface useful candidates with visible reasons, keep reviewer workload controlled, and preserve enough diagnostics to improve the engine over time.

The main tradeoff is:

```text
high recall vs reviewability
```

For v1, reviewability wins when the system would otherwise flood Sorters/Organizers with low-value false positives.

## v0.4 - deterministic multipass

### Problem

A single threshold was too brittle. High thresholds missed difficult duplicates; low thresholds produced too many candidates.

### Decision

Add deterministic bands:

```text
exact
strict
standard
loose
```

### Reason

The engine needed more recall without pretending every candidate had equal strength.

### Result

The engine could retain weak candidates for analysis while marking stronger candidates separately.

## v0.5 - candidate hygiene

### Problem

Blank pages, separator sheets, cover sheets, and generic low-information pages can create large amounts of junk.

### Decision

Add low-information page annotation, suppression controls, and candidate budgets.

### Reason

The v1 user experience cannot have the main list dominated by pages that are technically similar but useless for duplicate review.

### Result

Low-information filtering became a core hygiene layer before AI escalation.

## v0.6 - embedding and provider scaffolding

### Problem

Some near-duplicates are semantically similar but not caught by exact/text/visual deterministic rules.

### Decision

Add embedding provider scaffolding, but keep embeddings downstream of deterministic nomination.

### Reason

Embedding every page by default is expensive, harder to govern, and may create candidate explosion. Deterministic nomination keeps the system explainable and bounded.

### Result

Embeddings became an optional support/rerank layer, not the first detector.

## v0.7 - tiered OCR route

### Problem

Scanned duplicates are v1-critical, but OCR can be slow, noisy, and provider-sensitive.

### Decision

Define a tiered OCR route:

```text
native PDF text
-> Tesseract OCR
-> selected OpenAI OCR fallback
```

### Reason

Cheap local OCR should be tried first. Provider OCR should require evidence and an escalation reason.

### Result

Pages carry OCR route metadata even when OCR is disabled or unavailable, so reports can show capability gaps.

## v0.7.5 - calibration artifacts

### Problem

The engine had candidate output, but it was hard to inspect why it missed must-match pairs or why false positives were noisy.

### Decision

Add calibration JSON/CSV artifacts:

```text
candidate summary
false-positive review
false-negative review
threshold sweep
```

### Reason

The next decisions should be based on measured failure modes, not intuition.

### Result

v0.7.5 became the calibration bridge before OCR, embeddings, and adjudicator work.

## v0.7.6 - v1 schema and visibility alignment

### Problem

The v0.7.5 output mixed candidate labels with queue routing. In particular, `low_information_ignore` appeared like a duplicate-status label even though v1 treats low-information candidates as hidden/separate output.

### Decision

Separate three concepts:

```text
engine_candidate_label
visibility
future adjudicator/human labels
```

### Reason

The UI and saved-review schema need to distinguish what the engine surfaced, what the adjudicator suggested, and what a human finally decided.

### Result

Candidate records now include:

```text
engine_candidate_label
adjudicator_suggested_label
human_final_label
visibility
visibility_reason
candidate_category
```

`low_information_ignore` remains only a truth/evaluation bucket. Low-information candidates are routed by `visibility=low_information`.

## v0.8.0 - OCR validation harness

### Problem

The v1 goal requires scanned duplicates to be actively handled, but previous releases could not clearly answer whether OCR was available, where it ran, whether it improved matching text, or which truth pairs remained OCR-dependent misses.

### Decision

Add OCR validation artifacts alongside the normal report and calibration outputs:

```text
ocr_validation.json
ocr_routes.csv
ocr_candidates.csv
ocr_truth_rows inside ocr_validation.json
```

Record OpenAI OCR fallback selection even in dry-run mode, so a run can show which pages would escalate and why before credentials or live provider calls are enabled.

### Reason

v0.8 should make OCR measurable before trying to tune OCR quality. The first question is not "is OCR perfect?" but "can we see the route, improvement, skip reason, and OCR-dependent recall impact?"

### Result

Pages now expose native/Tesseract/OpenAI OCR route fields, Tesseract capability reports include the installed version when available, and eval runs can produce OCR-specific diagnostics without making provider OCR mandatory.

## Next: v0.9 - live embeddings calibration

### Problem to solve next

After OCR improves `best_text`, deterministic candidates still need semantic reranking and confidence bands without embedding the entire corpus by default.

### Planned decision area

Validate deterministic-nominated embeddings on OCR-improved text, then measure whether recall improves without increasing the reviewer-facing candidate volume.

### Expected outputs

```text
embedding route report
embedding confidence bands
embedding reranking report
recall recovered by embeddings
false positives introduced by embeddings
provider usage report
```

## Open decisions

1. Whether the default main review threshold should remain `0.86` after OCR-enabled medium-corpus calibration.
2. Whether low-information exact duplicates should be hidden entirely or available in a secondary UI section by default.
3. Whether partial-overlap detection needs its own specialized detector or can be an adjudicator/reviewer label at first.
4. Which OCR provider behavior is acceptable for real medical-record batches once cost, speed, and privacy constraints are known.
5. Whether OpenAI OCR fallback should allow Tesseract-unavailable pages by default or only after Tesseract was attempted.

## v0.8.1 - OpenAI route governance

### Problem

The project may use one approved OpenAI integration for compliance, but one vendor/key must not become one vague all-purpose AI path. Vision OCR, embeddings, text adjudication, and future vision-pair adjudication have different purposes and risks.

### Decision

Add an AI route ledger and route-specific event metadata.

Routes are named explicitly:

```text
vision_ocr_extraction
text_embedding
text_adjudication
vision_pair_adjudication
```

OpenAI-compatible vision OCR and embeddings now record route events for dry-run skips, unavailable-provider skips, errors, and completed calls. Reports can emit `--ai-ledger-out` and `--ai-ledger-csv`.

### Reason

This keeps the architecture compliant with a single approved OpenAI provider while preserving internal separation of concerns:

```text
OCR creates text evidence.
Embeddings compare text evidence.
Adjudication interprets structured evidence.
Vision-pair adjudication remains a future hard-case route.
```

### Result

v0.8.1 can now answer:

```text
Which AI route was selected?
Why was it selected?
Was a provider call attempted?
Was it a dry run or unavailable skip?
Did it change extracted evidence or matching confidence?
Which model/provider was configured?
```

No extracted page text is written to the AI ledger by default.

## Next: v0.9 - live embeddings calibration

The v0.9 embedding calibration should use the new AI route ledger as the provider governance report while measuring whether embeddings improve recall without exploding candidate volume.


## v0.8.2 - Benchmark TUI

### Problem

Before changing detection behavior again, benchmark evidence needs to be easier to run and inspect. The current engine already emits JSON/CSV/HTML artifacts, but reading each file manually slows calibration and makes comparisons inconsistent.

### Decision

Add a dependency-free terminal UI and dashboard command.

Profiles:

```text
baseline
ocr
ocr-openai-dry-run
embeddings-dry-run
governance
```

The TUI writes every major report family into a benchmark output folder and records the exact command in `benchmark_command.json`.

### Reason

This keeps the next step focused on measurement instead of new model behavior. It also avoids adding a new TUI framework dependency that might be hard to install on locked-down company machines.

### Result

The benchmark path can now be run as:

```bash
dupe-engine tui --run --profile governance --dpi 150 --pdf-dir ./synthetic_corpus_v2_medium/pdfs --truth ./synthetic_corpus_v2_medium/synthetic_v2_truth_pairs.json --output-dir output/benchmarks/v082_medium_governance_150dpi
```

Existing outputs can be summarized with:

```bash
dupe-engine tui --summarize output/benchmarks/v082_medium_governance_150dpi
```

The final v1 UI is still a separate future deliverable. This TUI is only a benchmark/calibration helper.

## v0.8.4 - Truth-Aware Runs

### Decision

Truth files are optional. The engine must run without them.

### Why

Production batches will not have answer keys. Requiring `--truth` in the TUI made the benchmark path feel synthetic-only and created confusion. The correct shape is a single run path with optional evaluation attachment.

### Behavior

- Explicit `--truth` is strict and fails if missing/invalid.
- Omitted `--truth` triggers nearby auto-detection.
- Invalid auto-detected candidates are skipped with warnings.
- If no valid truth exists, candidate/OCR/ledger/review outputs still write.
- The dashboard clearly says evaluation metrics were skipped.

### Tradeoff

Auto-detection can only be trusted if schema validation is strict. v0.8.4 keeps validation strict and avoids treating group-level metadata as pair-level truth.

## v0.8.5 - OCR-live profile and Synthetic v2 paired benchmark rounds

Decision: add `ocr-live` instead of reusing `governance` for live OCR testing.

Reason: `governance` intentionally dry-runs OpenAI OCR and embeddings. Using it for live OCR testing made results look successful while provider attempts remained zero.

Decision: add `--no-truth-autodetect` and `--rounds truth-and-no-truth`.

Reason: production batches do not have truth files, but Synthetic v2 does. The paired run makes the same corpus produce both calibration metrics and production-like outputs without changing the core engine path.
