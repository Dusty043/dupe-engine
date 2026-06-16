# Pilot Smoke Test Guide

Use this guide to verify the review UI end-to-end before running a real batch.

The smoke test uses the bundled example run. It does not require an OpenAI key, does not process PDFs, and does not call any external service.

---

## Option A: Instant UI smoke test (bundled example run)

Opens a pre-built example run with 10 candidates and pre-rendered page images. Takes about 10 seconds.

```bash
dupe-engine review-ui \
  --run-dir examples/ui_run_example \
  --no-browser
```

Then open `http://127.0.0.1:8765` in a browser.

What to verify:

```text
[ ] Page loads without errors
[ ] Candidate list shows 10 candidates
[ ] Clicking a candidate shows side-by-side page preview
[ ] Page images load (should not show broken image placeholders)
[ ] Decision buttons respond (duplicate / not duplicate / partial overlap / unsure)
[ ] Decision persists after clicking (try refreshing the page)
[ ] Export/download works
[ ] Filter by queue bucket works
```

If all pass: the UI stack is working.

---

## Option B: Full pipeline smoke test (synthetic corpus, live OCR)

Runs the full engine on the small dev synthetic corpus. Requires an OpenAI key and takes 2–5 minutes.

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

dupe-engine compare-ab \
  examples/synthetic_v3/small_dev/received_records \
  examples/synthetic_v3/small_dev/ere_records \
  --work-dir output/smoke_test/work \
  --out output/smoke_test/results.json \
  --run-dir output/smoke_test/run \
  --dpi 150 \
  --ocr \
  --require-ocr \
  --openai-ocr \
  --openai-ocr-live \
  --require-openai-ocr \
  --openai-ocr-max-pages 10

dupe-engine review-ui \
  --run-dir output/smoke_test/run \
  --no-browser
```

Then open `http://127.0.0.1:8765`.

What to verify in addition to Option A:

```text
[ ] Run completed without errors
[ ] Page images generated at output/smoke_test/run/assets/page_images/
[ ] capabilities.json shows ocr: available, openai_ocr_fallback: available
[ ] metrics.json shows at least one candidate
```

---

## Option C: Browser upload smoke test (end-to-end with the UI job workflow)

Tests the full upload-and-run workflow. Requires an OpenAI key.

1. Start the review UI with no run pre-loaded:

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

dupe-engine review-ui \
  --workspace output/smoke_test_jobs \
  --no-browser
```

2. Open `http://127.0.0.1:8765`

3. Upload two small PDF folders using the browser upload form:
   - Received records: any small PDF folder (2–5 PDFs)
   - ERE records: any small PDF folder (2–5 PDFs)

4. Watch the job progress in the UI

5. Verify the review queue loads when the job completes

What to verify:

```text
[ ] Upload form accepts PDFs
[ ] Job starts and status updates in the UI
[ ] Progress stages advance (rendering → OCR → candidates → completed)
[ ] Review queue loads after completion
[ ] Decisions save and persist
[ ] No "Engine job failed" errors in the UI
```

If step 3 fails: check that the .env has a valid DUPE_OPENAI_API_KEY.

---

## Troubleshooting

### "OpenAI OCR key not set"

The server needs `DUPE_OPENAI_API_KEY` in the environment.

For Docker:

```bash
docker run --env-file /path/to/.env ...
```

For direct launch:

```bash
export DUPE_OPENAI_API_KEY="sk-..."
dupe-engine review-ui ...
```

### "Run folder does not exist"

The `--run-dir` path is wrong. Check the path is absolute or relative to the current working directory.

### Page images not loading

Check that `assets/page_images/` exists inside the run folder. If empty, the engine may have run with `--dpi 0` or DPI rendering was skipped.

### Job stuck at "running"

The server stores jobs in memory. If the server restarted mid-job, the job state is lost. Start a new job.

---

## Server health check

```bash
curl http://localhost:8765/api/status
```

Expected when no run is loaded:

```json
{"ok": true, "workspace_dir": "...", "has_run": false}
```

Expected when a run is loaded:

```json
{"ok": true, "workspace_dir": "...", "has_run": true}
```
