# Dupe Engine v0.10.4

**Dupe Engine v0.10.4** is a local-first duplicate-page review system for comparing incoming medical records against existing ERE records.

It is currently optimized for the v1 workflow:

```text
Received Medical Records
vs
ERE Medical Records
```

The engine finds duplicate, likely duplicate, possible duplicate, and partial-overlap page candidates. The review UI lets staff inspect candidates side-by-side, save reviewer decisions, and export results.

v0.10.4 is still v1-safe: OCR and OpenAI OCR fallback are required, while semantic/vector recall is optional, bounded, and evaluated separately from final duplicate decisions. The current accuracy path is:

```text
PDFs
-> native text extraction
-> Tesseract OCR for weak/scanned pages
-> selected OpenAI vision OCR rescue
-> deterministic duplicate/overlap candidates
-> optional bounded embedding recall
-> review UI
-> reviewer decisions / exports
```

Embeddings can now create bounded top-k recall candidates when explicitly enabled. LLM candidate detection and adjudication remain **v2 layers**: provisioned in config/schema, disabled, and non-blocking by default.

---



## v0.10.4 parallel candidate-generation calibration quick start

v0.10.4 keeps the v0.10.3 candidate-generation strategy and upgrades the loop display: `--max-parallel-runs 2 --progress tui` now renders one aggregate parent dashboard instead of falling back to plain logs. The loop still compares the current champion against candidate-generation challengers and lets the LLM write a metrics-only analysis report after each iteration.

Plan the next batch from an existing calibration folder:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0102 \
  --out-dir ./output/calibration/loop_v0104_plan \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 2 \
  --dry-run
```

Run the loop live:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0102 \
  --out-dir ./output/calibration/loop_v0104 \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 4 \
  --confirm-live-ai
```

See `docs/V0_10_4_PARALLEL_TUI_CALIBRATION.md` and `docs/V0_10_3_PARALLEL_CANDIDATE_CALIBRATION.md`.

## v0.10.0 LLM calibration analysis quick start

v0.10.0 keeps the calibration harness unchanged and adds an optional metrics-only LLM analysis layer at the end of a calibration run. It reads the scorecard, recommendations, false-negative reason counts, OCR fallback counts, and queue metrics, then writes a human-readable calibration readout. Raw OCR/document text is **not** included by default.

Run calibration with the analysis layer:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/generalization_v010 \
  --profile generalization \
  --llm-analysis \
  --confirm-live-ai
```

Analyze an existing calibration folder without rerunning jobs:

```bash
PYTHONPATH=src python -m dupe_engine.cli analyze-calibration \
  ./output/calibration/generalization_v010
```

Outputs:

```text
llm_analysis.md
llm_analysis.json
```

Use `--llm-analysis-dry-run` or `analyze-calibration --dry-run` to write the heuristic report without calling an LLM provider.


## v0.9.9b cross-corpus generalization quick start

v0.9.9b adds a 10-run cross-corpus generalization matrix. It runs the same five OCR/vector/queue settings against both v3 medium calibration and v4 calibration, then ranks configs by average recall and worst-case recall rather than by a single corpus win.

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --out-dir ./output/calibration/generalization_v099b \
  --profile generalization \
  --confirm-live-ai
```

Or use:

```bash
scripts/run_cross_corpus_generalization_v099b.sh
```

The key artifact is `recommended_configs.json`, especially `generalization_summary.best_generalized_config`. Use this to talk about calibration as a generalization check, not a one-corpus leaderboard.


## v0.9.9a v4 calibration quick start

v0.9.9a adds the packaged `synthetic_v4_calibration` corpus, a focused 5-run v4 calibration profile, and a cleaner multi-bar calibration TUI.

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v4_calibration \
  --truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --out-dir ./output/calibration/v4_v099a \
  --profile v4_calibration \
  --confirm-live-ai
```

Use `--progress plain` if your terminal does not render the dashboard cleanly.

## v0.9.9 focused calibration quick start

v0.9.9 keeps the v0.9.8b accuracy-first baseline and adds a focused fallback-rescue experiment instead of rerunning a broad matrix every time.

Run:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v099_focused \
  --profile focused_rescue \
  --confirm-live-ai
```

Or use:

```bash
scripts/run_medium_calibration_focused_v099.sh
```

The focused matrix compares current best cap150/conservative-vector behavior against post-candidate OCR rescue budgets and the experimental `hybrid_test` vector profile.

New docs:

```text
docs/V0_9_9_FALLBACK_RESCUE_AND_HYBRID_VECTOR.md
docs/SYNTHETIC_V4_HOLDOUT_SPEC.md
```

## v0.9.8b calibration harness quick start

v0.9.8b adds an accuracy-first calibration harness for OCR fallback, vector recall, and queue-routing sweeps. Use it when choosing v1 defaults instead of manually running one config at a time.

Plan only:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_plan \
  --profile accuracy_first \
  --dry-run
```

Live accuracy-first run with progress TUI:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_accuracy \
  --profile accuracy_first \
  --confirm-live-ai
```

Resume after a crash without rerunning completed runs:

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --out-dir ./output/calibration/medium_v098b_accuracy \
  --profile accuracy_first \
  --resume \
  --skip-existing \
  --confirm-live-ai
```

Main outputs:

```text
output/calibration/medium_v098b_accuracy/scorecard.csv
output/calibration/medium_v098b_accuracy/recommended_configs.json
output/calibration/medium_v098b_accuracy/runs/*/run_status.json
output/calibration/medium_v098b_accuracy/runs/*/false_negatives.csv
```

See `docs/V0_9_8B_ACCURACY_CALIBRATION.md`.


## Current version focus

v0.10.4 is the parallel calibration TUI release on top of the v0.10.3 candidate-generation engine. The engine path remains focused on:

- native text extraction
- Tesseract OCR
- selected OpenAI OCR sidecar evidence
- deterministic multiview candidate formation
- optional bounded embedding recall
- review UI outputs

The `calibrate-loop` command is still controlled config search. v0.10.4 keeps the candidate-generation knobs and adds an aggregate dashboard for two concurrent sub-runs when `--max-parallel-runs 2 --progress tui` is used. It writes per-iteration LLM/heuristic analysis and keeps the workstation cap at two workers.
- Budgeted fallback selection so the system does **not** scan every page with OpenAI.
- Progress files and OpenAI fallback audit outputs.

Older v0.8 docs and commands are still included for history, but this README is written for the current v0.9.8b flow.

---


## v0.9.8b vector / phase-eval additions

v0.9.8b adds the two pieces needed after OCR rescue and embeddings became active:

```text
1. Vector analysis instead of blind embedding comparisons
   - embed only OCR-usable pages
   - retrieve bounded nearest-neighbor neighborhoods
   - gate candidates by similarity, margin, reciprocity, source relation, and per-page caps

2. Phase-aware evaluation
   - strict_pair_eval keeps the old exact truth-pair score
   - ocr_rescue_eval measures evidence readiness after OCR/fallback
   - vector_retrieval_eval measures embedding recall as retrieval@k
   - review_queue_eval measures human review burden and queue coverage
   - unknown_prediction_buckets separates unjudged vector candidates from known negatives
```

The decision rules are documented in `docs/V0_9_7_DECISION_LOGIC.md`.

## What this system does

### It does

- Compare two PDF groups: Received records vs ERE records.
- Render and inspect PDF pages.
- Use native PDF text when usable.
- Use Tesseract OCR for scanned/weak-text pages.
- Use OpenAI vision OCR fallback on selected weak/vision-needed pages.
- Generate candidate duplicate/overlap pairs.
- Produce UI-ready run artifacts.
- Serve a local browser review UI.
- Save reviewer decisions to `review_decisions.json`.
- Export reviewed results.
- Run truth-based calibration on synthetic corpora.

### It does not do yet

- Delete or modify source PDFs.
- Make final legal/medical determinations.
- Provide production auth or multi-user review locking.
- Run embeddings by default. Bounded embedding recall is available only when explicitly enabled.
- Use LLM adjudication as a final decision layer.
- Host itself in a cloud production environment out of the box.

---

## Install

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

The core install includes the OpenAI dependency used by mandatory OpenAI OCR fallback. The `dev` extra installs the test runner.

Install the host Tesseract executable too. On macOS:

```bash
brew install tesseract
```

Check the CLI:

```bash
PYTHONPATH=src python -m dupe_engine.cli --help
```

or, after editable install:

```bash
dupe-engine --help
```

---

## Required configuration

v0.9.8b expects OCR and OpenAI OCR fallback to be available.

Set one unified OpenAI key:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
```

The standard OpenAI variable also works:

```bash
export OPENAI_API_KEY="your_key_here"
```

Route-specific overrides are still supported when needed:

```text
DUPE_OPENAI_OCR_API_KEY
DUPE_EMBEDDINGS_API_KEY
DUPE_LLM_CANDIDATE_API_KEY
DUPE_ADJUDICATOR_API_KEY
```

The current default v1 contract is:

```text
DUPE_OCR_ENABLED=true
DUPE_REQUIRE_OCR=true
DUPE_OPENAI_OCR_ENABLED=true
DUPE_REQUIRE_OPENAI_OCR=true
DUPE_OPENAI_OCR_DRY_RUN=false
```

Run the doctor check:

```bash
PYTHONPATH=src python -m dupe_engine.cli doctor
```

A healthy setup should show OCR and OpenAI fallback as available and required:

```text
ocr: available
  required: true

tesseract_ocr: available
  required: false

openai_ocr_fallback: available
  required: true
```

If the OpenAI key is missing, `doctor` should fail loudly before you spend time on a batch run.

---

## OpenAI OCR fallback is mandatory but budgeted

Mandatory fallback does **not** mean every page is sent to OpenAI.

It means:

```text
OpenAI fallback must be configured and available.
Only selected weak/vision-needed pages are sent.
Selection is capped by budget.
Skipped eligible pages are reported.
```

v0.9.8b defaults:

```text
DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
DUPE_OPENAI_OCR_MAX_PAGES_PER_DOCUMENT=5
DUPE_OPENAI_OCR_ALLOW_LOW_INFORMATION_PAGES=true
DUPE_OPENAI_OCR_LOW_INFORMATION_PENALTY=true
DUPE_OPENAI_OCR_ACCEPT_CLEANER_SHORTER_TEXT=true
```

Supported selection modes:

| Mode | Behavior |
|---|---|
| `candidate_based` | Conservative legacy behavior: only weak pages already inside strong candidates. |
| `weak_pages` | Select weak/missing-text pages after Tesseract. |
| `vision_expected` | Select pages that metadata/routes suggest need vision fallback. |
| `weak_pages_or_vision_expected` | Current default: candidate pages first, then weak/vision pages up to budget. |

Example override:

```bash
export DUPE_OPENAI_OCR_SELECTION_MODE=weak_pages_or_vision_expected
export DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=50
```

For a more aggressive calibration run:

```bash
export DUPE_OPENAI_OCR_MAX_PAGES_PER_JOB=100
```

For old conservative behavior:

```bash
export DUPE_OPENAI_OCR_SELECTION_MODE=candidate_based
```

---

## Optional bounded embedding recall

Embeddings remain disabled by default. To test the v0.9.8b semantic recall path, enable them explicitly:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
export DUPE_EMBEDDINGS_ENABLED=true
export DUPE_EMBEDDINGS_DRY_RUN=false
```

Useful defaults:

```text
DUPE_EMBEDDINGS_MODEL=text-embedding-3-small
DUPE_EMBEDDINGS_CANDIDATE_TOP_K=5
DUPE_EMBEDDINGS_SIMILARITY_THRESHOLD=0.88
DUPE_EMBEDDINGS_MIN_MARGIN=0.03
DUPE_EMBEDDINGS_MAX_CANDIDATES_PER_PAGE=2
DUPE_EMBEDDINGS_MIN_TEXT_CHARS=120
DUPE_EMBEDDINGS_MAX_PAGES_PER_JOB=1000
DUPE_EMBEDDINGS_CREATE_CANDIDATES=true
DUPE_EMBEDDINGS_SKIP_EXACT_MATCHES=true
DUPE_REQUIRE_EMBEDDINGS=false
```

The embedding pass is bounded:

```text
only pages with usable post-OCR text are embedded
only top-k vector neighbors per page are considered
margin/reciprocity/source-relation gates prevent blind candidate spraying
exact deterministic pairs are skipped
embedding-only candidates are labeled possible_duplicate or needs_review
LLM adjudication still does not run
```

Run medium with OCR rescue plus vector-neighborhood embeddings:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
export DUPE_EMBEDDINGS_ENABLED=true
export DUPE_EMBEDDINGS_DRY_RUN=false

PYTHONPATH=src python -m dupe_engine.cli eval-all \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --work-dir ./output/work/medium_calibration_v3_ocr_vector \
  --out ./output/medium_calibration_v3_ocr_vector/results.json \
  --eval-out ./output/medium_calibration_v3_ocr_vector/eval.json \
  --phase-eval-out ./output/medium_calibration_v3_ocr_vector/phase_eval.json \
  --run-dir ./output/runs/medium_calibration_v3_ocr_vector \
  --dpi 150 \
  --ocr \
  --require-ocr \
  --openai-ocr \
  --openai-ocr-live \
  --require-openai-ocr \
  --openai-ocr-max-pages 50 \
  --openai-ocr-max-pages-per-document 5 \
  --embeddings \
  --embedding-top-k 5 \
  --embedding-similarity-threshold 0.88 \
  --embedding-min-margin 0.03 \
  --embedding-max-candidates-per-page 2
```

Or use the packaged script:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
export DUPE_EMBEDDINGS_ENABLED=true
export DUPE_EMBEDDINGS_DRY_RUN=false
scripts/run_medium_accuracy_v097.sh
```

---

## Fast UI smoke test

Open the bundled example run. This does not run OCR or call OpenAI; it only checks the review UI.

```bash
PYTHONPATH=src python -m dupe_engine.cli review-ui \
  --run-dir examples/ui_run_example
```

If the browser does not open automatically, visit the printed local URL, usually:

```text
http://127.0.0.1:8765
```

Use this mode to test:

- Layout.
- Candidate queue.
- Side-by-side review.
- Expanded comparison mode.
- Decision buttons.
- `review_decisions.json` writes.
- CSV/JSON export.

---

## Browser upload workflow

Start the local app without a prebuilt run folder:

```bash
PYTHONPATH=src python -m dupe_engine.cli review-ui
```

Then use the browser to upload PDFs into:

```text
Received Medical Records
vs
ERE Medical Records
```

The local server will:

1. Save uploaded PDFs into a local workspace.
2. Run the engine as a `compare-ab` job.
3. Write a normal run folder.
4. Load the completed review queue.
5. Save reviewer decisions back into that run folder.

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

Choose a workspace explicitly:

```bash
PYTHONPATH=src python -m dupe_engine.cli review-ui \
  --workspace ./output/review_ui_jobs \
  --host 127.0.0.1 \
  --port 8765
```

---

## Run a client-style A/B comparison manually

Use this when you already have two folders of PDFs.

```text
received_records/  = incoming records
ere_records/       = existing ERE records
```

Run:

```bash
PYTHONPATH=src python -m dupe_engine.cli compare-ab \
  ./received_records \
  ./ere_records \
  --work-dir ./output/work/received_vs_ere \
  --out ./output/received_vs_ere/results.json \
  --progress-dir ./output/runs/received_vs_ere \
  --fallback-audit-out ./output/received_vs_ere/fallback_audit.json \
  --fallback-audit-csv ./output/received_vs_ere/fallback_pages.csv \
  --run-dir ./output/runs/received_vs_ere \
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
PYTHONPATH=src python -m dupe_engine.cli review-ui \
  --run-dir ./output/runs/received_vs_ere
```

---

## Bundled v3 test corpora

v0.9.8b includes two OCR-heavy synthetic corpora:

```text
examples/synthetic_v3/small_dev
examples/synthetic_v3/medium_calibration
```

Use them for local testing and calibration.

### Small dev corpus

Fastest real engine loop:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
scripts/run_small_dev_v3_ocr.sh
```

Open the run:

```bash
PYTHONPATH=src python -m dupe_engine.cli review-ui \
  --run-dir output/runs/small_dev_v3_ocr
```

### Medium calibration corpus

Main OCR/fallback stress test:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
scripts/run_medium_calibration_v3_ocr.sh
```

Open the run:

```bash
PYTHONPATH=src python -m dupe_engine.cli review-ui \
  --run-dir output/runs/medium_calibration_v3_ocr
```

The medium run writes:

```text
output/medium_calibration_v3_ocr/results.json
output/medium_calibration_v3_ocr/eval.json
output/medium_calibration_v3_ocr/ocr_validation.json
output/medium_calibration_v3_ocr/ocr_routes.csv
output/medium_calibration_v3_ocr/ocr_candidates.csv
output/medium_calibration_v3_ocr/fallback_audit.json
output/medium_calibration_v3_ocr/fallback_pages.csv
output/runs/medium_calibration_v3_ocr/
```

---

## Fallback sweep testing

Use the sweep when you want to compare recall/runtime/call count across fallback budgets.

```bash
export DUPE_OPENAI_API_KEY="your_key_here"
scripts/run_medium_fallback_sweep.sh
```

Default caps:

```text
0 25 50 100
```

Output:

```text
output/fallback_sweep_medium/sweep_summary.csv
```

The summary includes:

```text
cap
recall
true_positive_count
false_negative_count
selected fallback pages
attempted fallback pages
usable fallback pages
improved fallback pages
eligible pages skipped due to budget
```

You can override the caps:

```bash
CAPS="0 10 25 50" scripts/run_medium_fallback_sweep.sh
```

This is the main v0.9.8b test for proving that fallback improves recall without scanning everything.

---

## Progress and fallback audit outputs

When a run has `--run-dir` or `--progress-dir`, v0.9.8b writes:

```text
progress.json
progress_events.jsonl
```

These files let the UI show job progress during long batches.

When a run has `--run-dir` or explicit fallback audit outputs, v0.9.8b also writes:

```text
fallback_audit.json
fallback_pages.csv
```

Use these to answer:

- Which pages were eligible for OpenAI fallback?
- Which pages were selected?
- Which pages were skipped due to budget?
- Which pages were attempted?
- Which pages became usable?
- Which pages improved the evidence?
- Why was a page selected or skipped?

Quick inspection:

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('output/runs/medium_calibration_v3_ocr/fallback_audit.json')
data = json.loads(p.read_text())
print(json.dumps(data.get('summary', data), indent=2))
PY
```

---

## Run artifact contract

The UI consumes a run folder, not engine internals.

A normal run folder contains:

```text
run_manifest.json
pages.json
candidates.json
candidate_pairs.json
capabilities.json
metrics.json
truth_eval.json          # when truth/eval is available
progress.json
progress_events.jsonl
fallback_audit.json
fallback_pages.csv
review_decisions.json
assets/page_images/
```

This is the boundary between the engine and the UI:

```text
engine produces run artifacts
UI consumes run artifacts
reviewer decisions write back to review_decisions.json
```

That split is intentional. It lets the engine continue changing without rebuilding the UI around internal code.

---

## Review decisions

Reviewer decisions are stored in:

```text
<run-dir>/review_decisions.json
```

Decision labels:

```text
duplicate
likely_duplicate
possible_duplicate
partial_overlap
not_duplicate
needs_review
```

The current decision model is intentionally lightweight. It is enough for v1 review state, export, and calibration feedback. It is not yet a full multi-user approval/audit system.

---

## Truth evaluation

Production batches do not have truth files. Synthetic corpora do.

For truth-based evaluation, use `eval-all` or the provided scripts. Example:

```bash
PYTHONPATH=src python -m dupe_engine.cli eval-all \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --work-dir ./output/work/medium_calibration_v3_ocr \
  --out ./output/medium_calibration_v3_ocr/results.json \
  --eval-out ./output/medium_calibration_v3_ocr/eval.json \
  --progress-dir ./output/runs/medium_calibration_v3_ocr \
  --fallback-audit-out ./output/medium_calibration_v3_ocr/fallback_audit.json \
  --fallback-audit-csv ./output/medium_calibration_v3_ocr/fallback_pages.csv \
  --ocr-validation-out ./output/medium_calibration_v3_ocr/ocr_validation.json \
  --ocr-route-csv ./output/medium_calibration_v3_ocr/ocr_routes.csv \
  --ocr-candidate-csv ./output/medium_calibration_v3_ocr/ocr_candidates.csv \
  --run-dir ./output/runs/medium_calibration_v3_ocr \
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

Key eval fields:

```text
recall_on_must_match
true_positive_count
false_negative_count
expected_negative_hits
partial_overlap_hits
recall_by_expected_min_layer
```

Use `recall_by_expected_min_layer` to decide whether remaining misses are OCR/fallback problems or future embedding/LLM problems.

---

## Candidate hygiene and budget controls

Defaults are tuned to keep review queues workable:

```text
DUPE_LOW_INFORMATION_FILTER_ENABLED=true
DUPE_SUPPRESS_LOW_INFORMATION_CANDIDATES=true
DUPE_MAX_CANDIDATES_PER_JOB=2000
DUPE_MAX_CANDIDATES_PER_PAGE=40
DUPE_MAIN_REVIEW_MIN_CONFIDENCE=0.86
DUPE_MAIN_REVIEW_MAX_CANDIDATES_PER_100_PAGES=50
```

Useful CLI overrides:

```bash
--max-candidates-per-job 1000
--max-candidates-per-page 25
--main-review-min-confidence 0.86
--main-review-max-candidates-per-100-pages 50
--disable-low-info-suppression
```

Do not turn on broad visual all-page matching for large batches unless you are intentionally stress-testing candidate volume:

```bash
--multipass-visual-all-pages
```

---

## v2 layers are non-blocking

These layers are provisioned but disabled by default:

```text
embeddings
LLM candidate detector
adjudicator agent
```

They should not block v1 OCR/fallback testing.

Current state:

- Embeddings can support/rerank selected deterministic candidates when enabled.
- The real v2 semantic recall layer still needs vector index/top-k candidate expansion.
- LLM adjudication is reserved for ambiguous same-template, partial-overlap, and hard-negative cases.

Only enable these when deliberately testing v2 behavior:

```bash
--embeddings
--llm-detector
--adjudicator
```

Only require them when you truly want the run to fail if the provider is unavailable:

```bash
--require-embeddings
--require-llm-detector
--require-adjudicator
```

---

## Repository map

Important files:

```text
src/dupe_engine/cli.py                  # CLI entrypoints
src/dupe_engine/config.py               # runtime config/env/flags
src/dupe_engine/capabilities.py         # doctor/capability checks
src/dupe_engine/engine.py               # pipeline orchestration
src/dupe_engine/ingest.py               # PDF rendering/native text/OCR routing input
src/dupe_engine/ocr.py                  # Tesseract + OpenAI fallback selection/execution
src/dupe_engine/matchers.py             # deterministic candidate generation
src/dupe_engine/review.py               # reviewer labels/visibility
src/dupe_engine/evaluation.py           # truth evaluation
src/dupe_engine/ui_artifacts.py         # run artifact contract
src/dupe_engine/review_ui_server.py     # local review UI server
src/dupe_engine/review_ui_static/       # browser UI assets
```

Useful docs:

```text
docs/MEDICAL_RECORDS_SORTER_V0_9_DESIGN_SPEC.md
docs/UI_RUN_ARTIFACTS.md
docs/V0_9_7_TESTING_NOTES.md
docs/OCR_SETUP_AND_TESTING_GUIDE.md
docs/OPENAI_PROVIDER_NOTES.md
docs/ROADMAP.md
```

Legacy handoff files remain in the repo for project history, but the v0.9.9a path should start from this README.

---

## Tests

Run the test suite:

```bash
PYTHONPATH=src pytest
```

Expected for the packaged v0.9.9b build:

```text
91 passed
```

---

## PHI and deployment notes

The current system is local-first. For a v1 pilot, the natural deployment target is an internal server or VM with mounted internal storage, not a serverless frontend-only deployment.

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

The engine generates review assistance. Human reviewers still make final workflow decisions.
