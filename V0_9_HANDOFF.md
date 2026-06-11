# v0.9 Handoff — Integrated Review UI

## Summary

v0.9 adds the first integrated local review UI for **Medical Records Sorter Assist**.

The engine core remains the v0.8.1 duplicate engine with v0.8.6 UI run artifacts. v0.9 adds a browser-based local review layer that consumes a `--run-dir` folder and writes reviewer decisions back to `review_decisions.json`.

## New command

```bash
PYTHONPATH=src dupe-engine review-ui --run-dir examples/ui_run_example
```

Optional:

```bash
PYTHONPATH=src dupe-engine review-ui \
  --run-dir output/runs/small_dev_086 \
  --host 127.0.0.1 \
  --port 8765 \
  --no-browser
```

## What the UI does

- Loads `run_manifest.json`, `pages.json`, `candidates.json`, `capabilities.json`, `metrics.json`, optional `truth_eval.json`, and `review_decisions.json`.
- Serves page preview assets from `assets/page_images/`.
- Presents the workflow as **Received Medical Records vs ERE Medical Records**.
- Shows run summary and capability status.
- Provides a filtered candidate review queue.
- Opens candidates side by side.
- Shows engine explanation and signals.
- Saves reviewer decisions through the local Python API.
- Exports CSV and decisions JSON from the browser.

## Local API routes

The new `review-ui` command starts a dependency-free stdlib HTTP server.

Routes:

```text
GET  /api/health
GET  /api/run
GET  /api/review-decisions
POST /api/review-decisions
GET  /run-artifacts/<path>
```

Decision writes are validated against the allowed labels:

```text
duplicate
likely_duplicate
possible_duplicate
partial_overlap
not_duplicate
needs_review
```

## Files added

```text
src/dupe_engine/review_ui_server.py
src/dupe_engine/review_ui_static/index.html
src/dupe_engine/review_ui_static/styles.css
src/dupe_engine/review_ui_static/app.js
docs/MEDICAL_RECORDS_SORTER_V0_9_DESIGN_SPEC.md
examples/ui_run_example/
scripts/open_review_ui_example.sh
```

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

OCR extras remain optional:

```bash
pip install -e '.[ocr,dev]'
```

## Smoke test

```bash
PYTHONPATH=src dupe-engine review-ui --run-dir examples/ui_run_example --no-browser
```

Then open the printed local URL.

## Current limitations

- This is local-first, not a deployed multi-user app.
- It serves one run folder at a time.
- It writes a single `review_decisions.json` file.
- It does not yet launch engine jobs from the browser.
- The Received/ERE source labels are inferred from group `A`/`B`, `source_A`/`source_B`, `received`, or `ere` naming. All-pairs runs fall back to Left/Right where source identity is unavailable.
- No auth, locking, or database storage yet.

## Recommended next steps

1. Run small_dev through v0.9 and review 20–30 candidates in the UI.
2. Patch any artifact fields that feel awkward in the UI.
3. Add a two-folder launch flow: Received folder + ERE folder -> `compare-ab --run-dir` -> open UI.
4. Run medium_calibration after the reviewer loop feels usable.
5. Only then tune thresholds heavily.
