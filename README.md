# Dupe Engine v0.10.9

**Dupe Engine v0.10.9** is a local-first duplicate-page review system for comparing incoming medical records against existing ERE records.

Workflow:

```text
Received Medical Records
vs
ERE Medical Records
```

The engine finds duplicate, likely duplicate, possible duplicate, and partial-overlap page candidates. The review UI lets staff inspect candidates side-by-side, save reviewer decisions, and export results.

---

## How it works

```text
PDFs
-> native text extraction
-> Tesseract OCR for weak/scanned pages
-> selected OpenAI vision OCR rescue (budgeted)
-> deterministic duplicate/overlap candidates
-> optional bounded embedding recall
-> [v0.10.9] embedding precision reranker
-> review UI
-> reviewer decisions / exports
```

v0.10.9 is v1-safe: OCR and OpenAI OCR fallback are required. Semantic/vector recall is optional, bounded, and gated by the **embedding precision reranker** that demotes or drops low-confidence embedding candidates before they reach the review queue.

LLM candidate detection and adjudication are **v2 layers**: provisioned in config/schema, disabled, and non-blocking by default.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Install Tesseract on macOS:

```bash
brew install tesseract
```

Check the CLI:

```bash
dupe-engine --help
```

---

## Required configuration

Set your OpenAI key:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
```

The standard OpenAI variable also works:

```bash
export OPENAI_API_KEY="your_key_here"
```

Route-specific overrides (optional):

```text
DUPE_OPENAI_OCR_API_KEY
DUPE_EMBEDDINGS_API_KEY
DUPE_LLM_CANDIDATE_API_KEY
DUPE_ADJUDICATOR_API_KEY
```

Run the doctor check:

```bash
dupe-engine doctor
```

A healthy v1 setup shows:

```text
ocr: available
  required: true

tesseract_ocr: available
  required: false

openai_ocr_fallback: available
  required: true
```

---

## Pilot production launch

Start the review UI in production mode:

```bash
dupe-engine review-ui \
  --workspace /data/review_ui_jobs \
  --host 0.0.0.0 \
  --port 8765 \
  --no-browser
```

Or via Docker (preferred for server deploys):

```bash
docker run -d \
  --name dupe-engine-review \
  -p 8765:8765 \
  --env-file /path/to/.env \
  -v /data/review_ui_jobs:/data/review_ui_jobs \
  -v /data/runs:/data/runs \
  dupe-engine-worker:v0.10.9 \
  dupe-engine review-ui \
    --workspace /data/review_ui_jobs \
    --host 0.0.0.0 \
    --port 8765 \
    --no-browser
```

Do **not** pass `--run-dir` in production. That flag pre-loads a specific past run for debug/dev use only. Without it, the UI starts clean and loads a run automatically after each job completes.

Check that the server is up:

```bash
curl http://localhost:8765/api/status
```

Expected:

```json
{"ok": true, "workspace_dir": "/data/review_ui_jobs", "has_run": false}
```

---

## Browser upload workflow

Start the UI without a prebuilt run folder:

```bash
dupe-engine review-ui
```

Then use the browser to upload PDFs:

```text
Received Medical Records
vs
ERE Medical Records
```

The server will:

1. Save uploaded PDFs into a local workspace
2. Run the engine as a `compare-ab` job
3. Write a normal run folder
4. Load the completed review queue
5. Save reviewer decisions back into that run folder

Default browser-job layout:

```text
output/review_ui_jobs/<job_id>/
  input/
    received_records/
    ere_records/
  work/
  run/
    run_manifest.json
    pages.json
    candidates.json
    candidate_pairs.json
    capabilities.json
    metrics.json
    progress.json
    progress_events.jsonl
    fallback_audit.json
    fallback_pages.csv
    review_decisions.json
    assets/page_images/
  results.json
```

---

## Run an A/B comparison manually

Use when you already have two folders of PDFs:

```bash
dupe-engine compare-ab \
  ./received_records \
  ./ere_records \
  --work-dir ./output/work/received_vs_ere \
  --out ./output/received_vs_ere/results.json \
  --run-dir ./output/runs/received_vs_ere \
  --fallback-audit-out ./output/received_vs_ere/fallback_audit.json \
  --fallback-audit-csv ./output/received_vs_ere/fallback_pages.csv \
  --dpi 150 \
  --ocr \
  --require-ocr \
  --openai-ocr \
  --openai-ocr-live \
  --require-openai-ocr \
  --openai-ocr-max-pages 50 \
  --openai-ocr-selection-mode weak_pages_or_vision_expected \
  --tesseract-profiles standard
```

Open the completed run:

```bash
dupe-engine review-ui --run-dir ./output/runs/received_vs_ere
```

---

## OpenAI OCR fallback

Mandatory fallback does **not** mean every page is sent to OpenAI. Only selected weak/vision-needed pages are sent, capped by budget. Skipped eligible pages are reported.

Current defaults:

```text
DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT=5
```

Selection modes:

| Mode | Behavior |
|---|---|
| `candidate_based` | Conservative: only weak pages already inside strong candidates |
| `weak_pages` | Select weak/missing-text pages after Tesseract |
| `vision_expected` | Select pages that metadata suggests need vision fallback |
| `weak_pages_or_vision_expected` | Current default: candidate pages first, then weak/vision pages up to budget |

---

## v0.10.9 embedding precision reranker

The reranker gates pure-embedding candidates (found only by semantic similarity, not deterministic multiview) before they reach the review queue.

Enable:

```bash
export DUPE_EMBEDDING_RERANKER_ENABLED=true
export DUPE_EMBEDDING_RERANKER_ACTION=demote   # or: drop
export DUPE_EMBEDDING_RERANKER_MIN_CONFIDENCE=0.80
```

How it works:

```text
For each pure-embedding candidate:
  - Compute a precision score from base confidence +/- OCR/tesseract/same-doc adjustments
  - score >= min_confidence: pass through unchanged
  - score < min_confidence + action=demote: lower confidence to 0.49, route to calibration_only
  - score < min_confidence + action=drop: set confidence to 0.0, route to calibration_only (audit trail preserved)
```

Offline simulation tool (no engine run required):

```bash
python tools/v0109_reranker_sim.py /path/to/candidate_summary.csv \
  --min-confidence 0.80 \
  --action demote \
  --threshold-start 0.80 \
  --threshold-end 0.94 \
  --threshold-step 0.02
```

See `docs/V0_10_9_SEMANTIC_RERANKER_PLAN.md` for design details.

---

## Optional bounded embedding recall

Embeddings are disabled by default. To enable:

```bash
export DUPE_EMBEDDINGS_ENABLED=true
export DUPE_EMBEDDINGS_DRY_RUN=false
```

Key defaults:

```text
DUPE_EMBEDDINGS_MODEL=text-embedding-3-small
DUPE_EMBEDDINGS_CANDIDATE_TOP_K=5
DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD=0.88
DUPE_EMBEDDINGS_MIN_MARGIN=0.03
DUPE_EMBEDDINGS_MAX_CANDIDATES_PER_PAGE=2
DUPE_EMBEDDINGS_MIN_TEXT_CHARS=120
DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB=1000
```

The embedding pass is bounded: only OCR-usable pages are embedded, only top-k neighbors per page are considered, and exact deterministic pairs are skipped.

---

## Calibration harness

Run a calibration sweep against a synthetic corpus:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/run \
  --profile generalization \
  --confirm-live-ai
```

Run parallel calibration loop:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/loop \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 4 \
  --confirm-live-ai
```

Key outputs:

```text
scorecard.csv
recommended_configs.json
runs/*/run_status.json
runs/*/false_negatives.csv
```

Use `recommended_configs.json > generalization_summary.best_generalized_config` to pick v1 defaults. Calibration is a generalization check across both corpora, not a one-corpus leaderboard.

---

## Fast UI smoke test

Test the review UI without running OCR or calling OpenAI:

```bash
dupe-engine review-ui --run-dir examples/ui_run_example
```

Visit `http://127.0.0.1:8765`. Use this to test: layout, candidate queue, side-by-side review, decision buttons, `review_decisions.json` writes, CSV/JSON export.

---

## Candidate hygiene defaults

```text
DUPE_LOW_INFORMATION_FILTER_ENABLED=true
DUPE_SUPPRESS_LOW_INFORMATION_CANDIDATES=true
DUPE_MAX_CANDIDATES_PER_JOB=2000
DUPE_MAX_CANDIDATES_PER_PAGE=40
DUPE_MAIN_REVIEW_MIN_CONFIDENCE=0.86
DUPE_MAIN_REVIEW_MAX_CANDIDATES_PER_100_PAGES=50
```

---

## What this system does

### It does

- Compare two PDF groups: Received records vs ERE records
- Use native PDF text when available
- Use Tesseract OCR for scanned/weak-text pages
- Use budgeted OpenAI vision OCR fallback on selected weak pages
- Generate candidate duplicate/overlap pairs
- Gate embedding-only candidates with the precision reranker
- Serve a local browser review UI
- Save reviewer decisions to `review_decisions.json`
- Export reviewed results
- Run truth-based calibration on synthetic corpora

### It does not do yet

- Delete or modify source PDFs
- Make final legal/medical determinations
- Provide production auth or multi-user review locking
- Run embeddings by default (opt-in only)
- Use LLM adjudication as a final decision layer
- Host itself in a cloud environment out of the box

---

## Run artifact contract

The UI consumes a run folder, not engine internals.

```text
run_manifest.json
pages.json
candidates.json
candidate_pairs.json
capabilities.json
metrics.json
truth_eval.json          (when truth/eval is available)
progress.json
progress_events.jsonl
fallback_audit.json
fallback_pages.csv
review_decisions.json
assets/page_images/
```

The engine produces run artifacts; the UI consumes them. That split lets the engine evolve without rebuilding the UI around internals.

---

## Review decisions

Stored in `<run-dir>/review_decisions.json`.

Decision labels:

```text
duplicate
likely_duplicate
possible_duplicate
partial_overlap
not_duplicate
needs_review
```

---

## Repository map

```text
src/dupe_engine/cli.py                  CLI entrypoints
src/dupe_engine/config.py               runtime config / env / flags
src/dupe_engine/capabilities.py         doctor / capability checks
src/dupe_engine/engine.py               pipeline orchestration
src/dupe_engine/ingest.py               PDF rendering / native text / OCR routing
src/dupe_engine/ocr.py                  Tesseract + OpenAI fallback selection/execution
src/dupe_engine/matchers.py             deterministic candidate generation
src/dupe_engine/embedding_reranker.py   v0.10.9 embedding precision reranker
src/dupe_engine/calibration_harness.py  calibration loop / sweep harness
src/dupe_engine/review.py               reviewer labels / visibility
src/dupe_engine/evaluation.py           truth evaluation
src/dupe_engine/ui_artifacts.py         run artifact contract
src/dupe_engine/review_ui_server.py     local review UI server
src/dupe_engine/review_ui_static/       browser UI assets
tools/v0109_reranker_sim.py             offline reranker simulation
```

Key docs:

```text
docs/ARCHITECTURE.md
docs/V0_10_9_SEMANTIC_RERANKER_PLAN.md
docs/UI_RUN_ARTIFACTS.md
docs/V0_9_7_DECISION_LOGIC.md
docs/OCR_SETUP_AND_TESTING_GUIDE.md
docs/OPENAI_PROVIDER_NOTES.md
docs/ROADMAP.md
```

---

## Tests

```bash
PYTHONPATH=src pytest
```

---

## PHI and deployment notes

The current system is local-first. For a v1 pilot, the natural deployment target is an internal server or VM with mounted internal storage.

Recommended pilot shape:

```text
internal server / VM
Python app serves the UI
engine jobs run server-side
PDFs and run artifacts stay on internal storage
reviewers access via internal URL
```

Avoid enabling text previews or PHI logging on real records unless explicitly approved:

```text
DUPE_INCLUDE_TEXT_PREVIEW=false
DUPE_LOG_PHI=false
DUPE_PERSIST_EXTRACTED_TEXT=false
```

The engine generates review assistance. Human reviewers make final workflow decisions.
