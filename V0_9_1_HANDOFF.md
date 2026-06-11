# v0.9.1 Handoff — Browser Upload and Local Job Runner

## Summary

v0.9.1 adds the missing Phase 2 UI flow: reviewers can start a **Received Medical Records vs ERE Medical Records** comparison directly from the browser.

The system is still local-first. The browser uploads PDFs to the local Python review UI server, the server stores them in a workspace, launches the existing `compare-ab` engine command, writes a normal `--run-dir`, and then the UI opens the completed review queue.

## New default command

```bash
PYTHONPATH=src dupe-engine review-ui
```

This opens the upload/start screen. Existing run-folder mode still works:

```bash
PYTHONPATH=src dupe-engine review-ui --run-dir examples/ui_run_example
```

Optional workspace/port settings:

```bash
PYTHONPATH=src dupe-engine review-ui \
  --workspace ./output/review_ui_jobs \
  --host 127.0.0.1 \
  --port 8765 \
  --no-browser
```

## Browser workflow

1. Upload PDFs under **Received Medical Records**.
2. Upload PDFs under **ERE Medical Records**.
3. Choose run options:
   - DPI, default `150`
   - Tesseract profiles, default `standard`
   - OCR enabled by default
   - optional broader visual pass
4. Click **Run Duplicate Check**.
5. The local server creates a job workspace and runs the engine.
6. When the job succeeds, the UI loads the generated review queue.
7. Reviewer decisions still save to `review_decisions.json`.

## Workspace layout

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
    review_decisions.json
    assets/page_images/
  results.json
```

## Local API additions

```text
GET  /api/jobs
GET  /api/jobs/<job_id>
POST /api/jobs
POST /api/clear-run
```

Existing routes remain:

```text
GET  /api/health
GET  /api/run
GET  /api/review-decisions
POST /api/review-decisions
GET  /run-artifacts/<path>
```

## Files changed

```text
src/dupe_engine/review_ui_server.py
src/dupe_engine/review_ui_static/app.js
src/dupe_engine/review_ui_static/styles.css
src/dupe_engine/cli.py
README.md
pyproject.toml
src/dupe_engine/__init__.py
tests/test_review_ui_server.py
```

## Current limitations

- Jobs are tracked in memory for the current local server session.
- Uploads are local-only and write to the configured workspace.
- The browser job runner uses the current Python interpreter and calls `python -m dupe_engine.cli compare-ab`.
- No multi-user auth, locking, or database-backed job history yet.
- Progress is coarse-grained: queued, running, succeeded, failed.

## Recommended next steps

1. Test with 2–3 small real-ish PDFs per bucket.
2. Test with `small_dev` subsets copied into Received/ERE buckets.
3. Add finer progress events later if needed.
4. After UI workflow feels stable, run `medium_calibration` through the flow.
