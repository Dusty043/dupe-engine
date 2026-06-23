# dupe-engine — Claude Code onboarding

## What this is

**dupe-engine** is a local-first duplicate medical-records review system built for the Emryx pilot at simple.biz. It ingests PDFs of received medical records and ERE records, finds duplicate/overlap page candidates using a multi-layer pipeline (text → OCR → optional embeddings), and serves a web-based review UI where staff inspect and decide on matches.

Owner: Dustin (dustin@simple.biz). Solo project — no other engineers.

---

## Current state (as of 2026-06-24)

- **Branch:** `feat/healing-harness` — open as PR #1 against `main`
- **Version:** 0.10.9
- **Status:** pilot-ready; not yet deployed to AWS
- **Tests:** 194 passing (one known pre-existing failure: `test_correct_token_passes` needs `pip install -e .`)

### What's in the PR (v0.10.8 + v0.10.9)

- **v0.10.8** — HIPAA §164.312 remediation: bearer-token auth on review UI, audit logging, PHI redaction, TLS guard
- **v0.10.9** — Healing harness (`dupe-engine heal`): 6-phase diagnosis-and-repair pipeline that reads a finished run's outputs, diagnoses FN root causes, and prescribes CLI flag changes to improve recall

---

## Architecture in one page

```
PDFs
  → native text extraction
  → Tesseract OCR (scanned/weak pages)
  → OpenAI vision OCR rescue (budgeted, required for v1)
  → deterministic candidates (TF-IDF, cosine, overlap)
  → optional embedding recall (bounded, gated by reranker)
  → review UI (React-like vanilla JS + Python Flask server)
  → reviewer decisions → export
  → [v0.10.9] healing harness reads outputs, prescribes config changes
```

LLM candidate detection and adjudication are **v2 layers** — provisioned in config but disabled.

### Key source files

| File | Purpose |
|------|---------|
| `src/dupe_engine/cli.py` | Entry point — all CLI commands dispatch here |
| `src/dupe_engine/config.py` | Config dataclass — all tuneable parameters |
| `src/dupe_engine/calibration.py` | Eval + `classify_false_negative_reason()` — canonical FN root-cause names |
| `src/dupe_engine/healing_harness.py` | 6-phase heal pipeline (Assess → Diagnose → Prescribe → Heal → Compare → Certify) |
| `src/dupe_engine/heal_prescriber.py` | Maps root causes → CLI flag changes |
| `src/dupe_engine/review_ui_server.py` | Flask server for the review UI |
| `src/dupe_engine/review_ui_static/app.js` | Review UI frontend (vanilla JS, ~2000 lines) |
| `src/dupe_engine/security.py` | Auth gate, PHI redaction, audit logging |
| `PILOT_AWS_DEPLOY_CHECKLIST.md` | AWS deployment runbook (all open questions answered) |
| `docs/INCIDENT_RESPONSE.html` | Interactive failure-mode + escalation model — open in browser |
| `CHANGELOG.md` | Release notes |
| `V0_10_9_HANDOFF.md` | Session handoff doc (gitignored, local only) |

---

## How to run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'

# Run tests
pytest

# Run a compare-ab job (OCR dry-run, no API key needed)
DUPE_REQUIRE_OPENAI_OCR=false DUPE_REQUIRE_OCR=false \
DUPE_OPENAI_OCR_DRY_RUN=true \
dupe-engine compare-ab \
  --source-a examples/synthetic_v3/small_dev/source_A \
  --source-b examples/synthetic_v3/small_dev/source_B \
  --truth examples/synthetic_v3/small_dev/truth_pairs.csv \
  --out /tmp/test-run

# Start the review UI (no real patient data)
DUPE_UI_AUTH_TOKEN=dev-token dupe-engine review-ui --workspace /tmp/ui-test
# → http://localhost:8765 (token: dev-token)

# Run the healing harness on a completed run
dupe-engine heal --run-dir /tmp/test-run --verbose
```

---

## Security / HIPAA

- **Never log PHI.** `DUPE_LOG_PHI=false` is the default. Don't change it.
- **`DUPE_STRICT_COMPLIANCE=true`** required in production — refuses to start without HTTPS.
- **Real patient data** (Bowers/Emryx) is in `/data/review_ui_jobs/` on oreochiserver. Don't touch it without Dustin.
- **Do not deploy to ECS/ECR** until `PILOT_AWS_DEPLOY_CHECKLIST.md` is complete.
- The OpenAI key in the session history is **compromised** — it has been rotated.

---

## Conventions Claude should follow

- **No mutations** — all data transformations return new objects
- **No comments** unless the WHY is non-obvious (workaround, hidden constraint, subtle invariant)
- **No features beyond the task** — don't add error handling for scenarios that can't happen
- **Snapshot versioning** for heal configs: `.heal/vN/config.json` in workspace — git stays clean
- **`_merge_flags()`** in `heal_prescriber.py` is the correct way to merge CLI flags — deduplicates by `--flag-name`, not by value (see ISSUE-001 in CHANGELOG)
- **`reason_missed` values** in `false_negatives.csv` use the long-form canonical names from `calibration.py::classify_false_negative_reason()` — not short aliases

---

## Pending work (not started)

- Periodic healer daemon — fires after N runs + M reviewer decisions, writes `heal_config.json` automatically
- `dupe-engine heal rollback --to vN`
- "Report a missed pair" button in review UI
- AWS pilot deployment (see `PILOT_AWS_DEPLOY_CHECKLIST.md`)

---

## Test corpus

`examples/synthetic_v3/small_dev/` — 18 PDFs, source_A–source_F, 53 truth pairs. source_A vs source_B has 5 known cross-group pairs. Safe to use for local testing; no real PHI.

---

## Key env vars

| Var | Purpose | Default |
|-----|---------|---------|
| `DUPE_OPENAI_API_KEY` | OpenAI key for OCR | (required for v1 runs) |
| `DUPE_UI_AUTH_TOKEN` | Review UI auth token | (required to start server) |
| `DUPE_LOG_PHI` | Log patient data | `false` |
| `DUPE_STRICT_COMPLIANCE` | Hard-stop without HTTPS | `false` (set `true` in prod) |
| `DUPE_REQUIRE_OPENAI_OCR` | Fail if OCR unavailable | `true` |
| `DUPE_OPENAI_OCR_DRY_RUN` | Skip real OCR calls | `false` |
| `DUPE_REQUIRE_OCR` | Fail if any OCR unavailable | `true` |
