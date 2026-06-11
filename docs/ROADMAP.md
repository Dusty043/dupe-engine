# Roadmap

## Completed through v0.8.2

- v0.1/v0.2: modular duplicate engine, capability reporting.
- v0.3: detector/adjudicator schema separation.
- v0.4: deterministic strict/standard/loose multipass candidate generation.
- v0.5: candidate hygiene, low-information suppression, candidate budgets, recursive corpus support.
- v0.6: OpenAI-compatible embedding provider and post-deterministic embedding detector path.
- v0.7: tiered OCR routing with Tesseract TSV/confidence and selected OpenAI OCR fallback.
- v0.7.5: reviewer buckets plus calibration JSON/CSV artifacts for candidate summary, false-positive review, false-negative review, and threshold sweep.
- v0.7.6: v1-aligned labels, visibility routing, low-information separation, and iteration decision log.
- v0.8.0: OCR validation harness, Tesseract capability version capture, OpenAI OCR dry-run selection reporting, OCR route/candidate/truth diagnostics, and an OCR setup/testing guide.
- v0.8.1: OpenAI route governance, AI call ledger JSON/CSV outputs, route-specific dry-run/skip/error/completion records, and documentation separating vision OCR extraction from embeddings/adjudication.
- v0.8.2: dependency-free benchmark TUI, standardized benchmark profiles, benchmark dashboard/summarizer, and reproducible benchmark command capture.

## Next likely versions

### v0.9: Live embeddings calibration

Goal: improve semantic/scanned-text recall without candidate explosion.

- Use improved `best_text` from OCR.
- Run OpenAI-compatible embeddings only on deterministic-nominated candidates by default.
- Add embedding reranking and confidence bands.
- Measure recall recovered by embeddings.
- Measure false positives introduced by embeddings.

### v0.10: Adjudicator agent

Goal: make review easier and reduce false-positive burden.

- Add adjudicator suggestions.
- Keep `engine_candidate_label`, `adjudicator_suggested_label`, and `human_final_label` separate.
- Add visible explanation and risk flags.
- Allow suggested `not_duplicate` without silently removing detector evidence.

### v0.11: UI pilot

Goal: make the workflow usable by non-technical Sorters/Organizers.

- Upload Group A PDFs.
- Upload Group B PDFs.
- Start job and show status.
- Show main/low-information/calibration candidate sections.
- Side-by-side page viewer.
- Save reviewer decisions.
- Export results.
- Record audit events.

### v0.12: Calibration and v1 hardening

Goal: prepare an internal pilot.

- Threshold profiles.
- Runtime profiles.
- Failure reports.
- Review decision schema.
- Artifact cleanup.
- Error handling and provider fallback.
- Capability manifest display.
