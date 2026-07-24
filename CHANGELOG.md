# Changelog

## [0.10.14] - 2026-07-24

### Added
- **Automatic post-job healing** (`worker_healing.py`): the worker now runs
  assess → diagnose → prescribe → apply → certify on every completed job,
  in-process, with no human needing to run `dupe-engine heal` by hand.
  Previously deferred because the healing harness's `--apply` step shells
  out to `dupe-engine eval-all` (a single-corpus engine mode) while the
  worker runs `run_ab_compare` (a two-directory received-vs-ERE mode) — the
  two don't share a config-building path. `_apply_prescription` bridges
  this: it replays a prescription's CLI flags through the CLI's own
  `build_config`, diffs the result against an env-only baseline to isolate
  just the prescription's effect, and re-applies only that diff to the
  job's actual config, preserving whatever per-job SQS overrides the
  original request had.
- Without a reviewer-feedback UI (still not built — see
  `docs/PROJECT_EPICS_AND_TASK_SIZING.md`), only queue-load and OCR-coverage
  issues can fire automatically; recall/precision-based diagnosis still
  needs truth or feedback data.
- Writes `heal_output/` (`prescription.json`, `heal_report.json`,
  `healed/results.json`) alongside the job's normal run artifacts, riding
  along in the existing S3 upload. **Never changes what a reviewer sees** —
  matches the CLI's own `--apply`, which also never mutates the original
  run in place, only a sibling `healed/` directory. A better-scoring healed
  re-run is a signal for a human to review, not something auto-applied to
  a live job.
- Fails open: any exception during healing is caught and logged
  (`heal_failed`) — it can never affect the job's own success.

## [0.10.13] - 2026-07-14

### Fixed
- Visual/perceptual-hash candidate matching (`multipass_visual_matches`)
  could flag pages as "likely duplicate" on visual similarity alone,
  ignoring extracted text entirely, whenever a page was routed into the
  bounded visual-rescue path — which happens for virtually every scanned
  page needing OCR, regardless of whether the resulting OCR text was
  actually good. On the Bedrock OCR pilot this surfaced as high-confidence
  false-positive matches between pages with distinct identifying content
  (e.g. a receipt vs. an unrelated cover sheet, matched at 96% purely on
  layout similarity). Now vetoes a visual-only match when both pages carry
  extracted identifying tokens (case/receipt/claimant IDs, dates, etc. via
  `source_key_tokens`) that share no overlap — visual similarity alone can
  no longer override clearly conflicting identifiers.

## [0.10.12] - 2026-07-10

### Fixed
- Review UI's `/api/run/load` only ever looked at a local
  `<workspace>/<job_id>/run` path — never present for AWS-processed jobs,
  since the worker runs in a separate ECS task and only uploads results to
  S3 (`output_prefix`). Every completed AWS job showed "No candidates in
  this queue" because the run folder didn't exist locally. Now downloads
  the job's `output_prefix` via `artifact_store.download_prefix` before
  validating/serving the run, if not already cached locally.

## [0.10.11] - 2026-07-09

### Fixed
- AWS worker marked completed jobs with `status="completed"`, but the
  frontend and every other completion path in the app (local-mode job
  runner, CLI engine, calibration harness) use `status="succeeded"`. The
  review UI's step tracker, spinner, and "load previous run" list all key
  off `status === 'succeeded'` — so AWS-processed jobs finished on the
  backend but the UI never recognized it, appearing permanently stuck on
  "Working...". Worker now sets `status="succeeded"` and `stage="completed"`
  to match the reference implementation.

## [0.10.10] - 2026-07-09

### Fixed
- `GET /api/jobs/<job_id>` 500'd in AWS mode after any job ran: DynamoDB
  returns `Decimal` for numeric fields (`pages_processed`, `match_count`,
  etc.), and `job_status._dynamo_deserialize` passed them through unconverted
  — `json.dumps` has no `Decimal` support. Now converts `Decimal` to
  `int`/`float` recursively on read.

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
