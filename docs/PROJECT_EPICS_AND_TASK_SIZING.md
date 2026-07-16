# Dupe Engine: Project Epics, Tasks, and Story Points

> Retrospective project map, traced from repository history through `main` at
> `ec50325` (2026-07-14). Story points estimate relative task size; they are
> not hours and were not recorded as the original delivery estimates.

## Sizing rules

Use the Fibonacci scale `1, 2, 3, 5, 8, 13`.

| SP | Meaning |
| ---: | --- |
| 1–2 | Tiny, well-understood change |
| 3 | Small, clear task |
| 5 | Medium task with some unknowns |
| 8 | Large task; consider splitting |
| 13 | Very large or fuzzy; split before scheduling |

Points belong on tasks. Epic and project totals are sums of task points:

```text
project total = sum(epic totals)
epic total    = sum(task points)
```

These are retrospective estimates for planning and comparison. They are not a
substitute for sprint velocity, and a 13-point item should be split before it
enters a sprint.

## Epic 1 — Core duplicate detection and OCR pipeline

Outcome: turn incoming and ERE medical-record PDFs into reliable duplicate,
likely-duplicate, possible-duplicate, and partial-overlap candidates.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Ingest PDFs, preserve page/source identity, and build run artifacts | 5 | `ingest.py`, `models.py`, `da40983` | Done |
| Implement deterministic multipass matching and candidate labels | 8 | `matchers.py`, `candidates.py`, `docs/DETERMINISTIC_MULTIPASS.md` | Done |
| Add tiered OCR with Tesseract quality routing and OpenAI rescue | 8 | `ocr.py`, `ocr_metrics.py`, `docs/V0_7_TIERED_OCR.md` | Done |
| Produce truth, metrics, false-positive, and false-negative evaluation artifacts | 5 | `evaluation.py`, `reporting.py`, `docs/V0_7_5_CALIBRATION.md` | Done |
| Maintain synthetic corpora and repeatable calibration fixtures | 5 | `examples/`, `docs/SYNTHETIC_V4_HOLDOUT_SPEC.md` | Done |

**Epic total: 31 SP**

## Epic 2 — Calibration, evaluation, and quality observability

Outcome: improve recall and precision using repeatable experiments rather than
one-off threshold guesses.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Add calibration loops, threshold sweeps, and candidate diagnostics | 8 | `calibration.py`, `calibration_loop.py`, `7ce3eae` | Done |
| Add benchmark profiles and a dependency-free calibration TUI | 3 | `tui.py`, `docs/V0_8_2_BENCHMARK_TUI.md` | Done |
| Run cross-corpus and holdout generalization checks | 5 | `docs/V0_9_9B_CROSS_CORPUS_GENERALIZATION.md`, `c5637fa` | Done |
| Add progress, fallback, capability, and calibration observability | 5 | `calibration_observability.py`, `fallback_audit.py`, `86d68e2` | Done |

**Epic total: 21 SP**

## Epic 3 — Secure reviewer workflow

Outcome: let reviewers inspect, decide, and export candidate results while
protecting PHI and recording operational evidence.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Add bearer-token auth, audit logging, PHI-safe logging, and TLS guard | 8 | `security.py`, `audit.py`, commit `3f09e05` | Done |
| Build upload, job progress, candidate queue, and side-by-side review UI | 8 | `review_ui_server.py`, `review_ui_static/`, commits `f16be2a`, `c8d7b7a` | Done |
| Persist reviewer identity, decisions, run history, and exports | 5 | `review.py`, `ui_artifacts.py`, commits `9a22d4e`, `b267a35` | Done |
| Exercise the authenticated UI and compliance boundary with tests | 5 | `tests/test_hipaa_remediation.py`, `tests/test_e2e_server.py` | Done |

**Epic total: 26 SP**

## Epic 4 — AWS pilot execution path

Outcome: run comparison jobs outside the UI process and make their results
available to reviewers.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Add isolated worker and SQS job queue integration | 8 | `worker.py`, `job_queue.py`, `Dockerfile.worker`, `65bec49` | Done |
| Store run artifacts in S3 and restore them for review | 5 | `artifact_store.py`, `PILOT_AWS_DEPLOY_CHECKLIST.md` | Done |
| Persist job status in DynamoDB and normalize returned numeric values | 5 | `job_status.py`, `86d68e2`, `CHANGELOG.md` v0.10.10 | Done |
| Reconcile worker/UI completion status and AWS run loading | 5 | `CHANGELOG.md` v0.10.11–v0.10.12, `de36190`, `0d37a96` | Done |

**Epic total: 23 SP**

## Epic 5 — Semantic recall and precision controls

Outcome: recover useful semantic matches without flooding reviewers with false
positives.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Add bounded embedding candidate detection after deterministic matching | 8 | `embedding_detector.py`, `35729cd`, `c02473d` | Done |
| Add embedding precision reranking and visibility controls | 8 | `embedding_reranker.py`, `docs/V0_10_9_SEMANTIC_RERANKER_PLAN.md`, `c5637fa` | Done |
| Add offline diagnostics, calibration artifacts, and pilot validation | 5 | `embedding_diagnostic.py`, `docs/V0108_NEXT_EXPERIMENT.md` | Done |
| Guard visual-only matches against conflicting identifying tokens | 3 | `hashing.py`, `matchers.py`, `ec50325`, `CHANGELOG.md` v0.10.13 | Done |

**Epic total: 24 SP**

## Epic 6 — Healing harness

Outcome: use completed run evidence and reviewer feedback to prescribe and
optionally apply bounded recall improvements.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Diagnose false-negative root causes and prescribe CLI changes | 8 | `healing_harness.py`, `heal_prescriber.py`, `1c751dd` | Done |
| Apply prescriptions, compare before/after metrics, and certify outcomes | 8 | `dupe-engine heal`, `V0_10_9_HANDOFF.md`, `CHANGELOG.md` v0.10.9 | Done |
| Add multi-cycle snapshots and rollback-safe configuration artifacts | 3 | `.heal/vN/config.json` behavior documented in `V0_10_9_HANDOFF.md` | Done |
| Test the healer across malformed inputs, feedback, and subprocess failures | 5 | `tests/test_098_calibration_harness.py`, `tests/test_calibration_diagnostics_v0108.py` | Done |

**Epic total: 24 SP**

## Epic 7 — Productization, deployment, and project knowledge

Outcome: make the system operable by teammates and repeatable on the target
server.

| Task | SP | Historical evidence | Status |
| --- | ---: | --- | --- |
| Keep CLI configuration, capability reporting, and provider boundaries explicit | 5 | `cli.py`, `config.py`, `capabilities.py`, `docs/ARCHITECTURE.md` | Done |
| Add Docker/server startup and deployment helpers | 3 | `docker-compose*.yml`, `scripts/deploy.sh`, `PILOT_SMOKE_TEST.md` | Done |
| Maintain version handoffs, release notes, roadmap, and incident guidance | 5 | `V0_*_HANDOFF.md`, `CHANGELOG.md`, `docs/ROADMAP.md` | Done |

**Epic total: 13 SP**

## Project total

| Epic | Total SP |
| --- | ---: |
| Core duplicate detection and OCR pipeline | 31 |
| Calibration, evaluation, and quality observability | 21 |
| Secure reviewer workflow | 26 |
| AWS pilot execution path | 23 |
| Semantic recall and precision controls | 24 |
| Healing harness | 24 |
| Productization, deployment, and project knowledge | 13 |
| **Project total** | **162 SP** |

## History trace

The repository’s committed history shows this sequence:

1. **v0.1–v0.8:** deterministic matching, candidate hygiene, embeddings,
   tiered OCR, calibration artifacts, route governance, and benchmark tooling.
   The durable summary is in `docs/ROADMAP.md` and the versioned handoffs.
2. **v0.10.8:** the recall-focused baseline was consolidated in `da40983`,
   followed by HIPAA remediation and isolated-worker controls in `3f09e05` and
   `65bec49`.
3. **v0.10.9:** semantic reranking and the six-phase healing harness were
   added, with the merge and handoff recorded in `c5637fa` and `1c751dd`.
4. **v0.10.10–v0.10.13:** production corrections fixed DynamoDB numeric
   serialization, AWS completion-state drift, remote artifact loading, and a
   visual-hash false-positive path (`86d68e2`, `de36190`, `0d37a96`, `ec50325`).
5. **Current boundary:** the roadmap and handoff still describe periodic
   healer automation, healer rollback, and a reviewer “report missed pair” UI
   action as deferred work. They are intentionally not included in the 162 SP
   historical total.

## Sprint use

Schedule tasks from the backlog against observed completed-task velocity. Do
not assign the 162 SP project total to one sprint, and do not put an epic-sized
number on a board card: estimate the task, then let the epic and project sums
roll up automatically.
