# Changelog

## [0.10.9] - 2026-06-23

### Added
- **Healing harness** (`dupe-engine heal`) — 6-phase diagnosis-and-repair pipeline:
  - **Assess**: reads `results.json` and optional truth/feedback; computes weighted health score (recall, precision, queue load, OCR coverage)
  - **Diagnose**: reads `reason_missed` from `false_negatives.csv`; classifies FN root causes (low info, OCR cap, OCR quality, embeddings missing, threshold, identity, queue overload); incorporates user-reported missed pairs from `--feedback` JSON
  - **Prescribe**: maps each root cause to concrete CLI flag changes (e.g. `--loose-tfidf-threshold 0.68`, `--embeddings`, `--embedding-reranker`)
  - **Heal** (`--apply`): re-runs the engine with prescribed flags via subprocess
  - **Compare**: side-by-side before/after recall, precision, queue load, health score
  - **Certify**: HEALED / IMPROVED / RESISTANT verdict with residual-issue summary
- **Multi-cycle healing** (`--iterations N`): loops assess→prescribe→apply until certified or iteration limit
- **Snapshot versioning**: each heal cycle saves `.heal/vN/config.json` in the workspace so git stays clean and configs are rollback-able
- **Separate feedback format** (`--feedback <file>`): JSON array of `{id_a, id_b, verdict}` pairs (`missed_duplicate` / `false_alarm`); distinct from `review_decisions.json`
- **Heal prescriber** (`heal_prescriber.py`): standalone prescription engine with per-root-cause logic, conservative recall-delta estimates, and deduplication of conflicting flags

### Changed
- `dupe-engine heal` dispatches before `build_config()` — no API keys required to run the healer

### Fixed
- subprocess stderr always captured in `--apply` mode (avoids NoneType on failed re-run inspection)
- Corrupt `results.json` now raises `ValueError` immediately instead of silently producing a zero-score assessment
- `false_negatives.csv` opened with explicit UTF-8 encoding and guarded against OSError / decode errors
- `_print_comparison` guarded against None recall/precision fields when baseline run has no truth data

## [0.10.8] - 2026-06-22

### Added
- HIPAA §164.312 remediation: bearer-token auth on review UI, audit logging, PHI field redaction in logs, TLS guard
- Browser token overlay for authenticated review UI sessions
- Dockerfile.worker and docker-compose.worker.yml for isolated worker control
- AWS pilot deploy checklist (PILOT_AWS_DEPLOY_CHECKLIST.md)

### Fixed
- Security hardening: all CRITICAL/HIGH/MEDIUM/LOW findings from security review
- Loading state reset on token submit so UI refreshes immediately
