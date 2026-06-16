# Pilot UI Improvements Sketch

This document sketches the minimum UI improvements needed before the pilot, and the post-pilot backlog.

---

## Current state (v0.10.9)

The review UI today:

- Serves a single run at a time (passed via `--run-dir` or set after a job completes)
- Shows a candidate list on the left, page previews on the right
- Has decision buttons (duplicate / not duplicate / partial overlap / needs review)
- Saves decisions to `review_decisions.json`
- Has basic filters by review bucket and decision status
- Shows job progress while a batch runs

What's missing for the pilot:

- No job list (no way to switch between runs without restarting the server)
- No plain-language queue labels (reviewers see engine-internal bucket names)
- No batch summary / export button visible to reviewers
- No clear indication of reranker demotions
- The start page when no run is loaded is an upload form — needs better UX

---

## Screen 1: Start / Job list (priority: HIGH)

When no run is loaded, show a job list instead of a raw upload form.

Layout:

```
┌─────────────────────────────────────────────────────────┐
│  Duplicate Checker                               [Upload]│
├─────────────────────────────────────────────────────────┤
│  Recent batches                                         │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Batch: received_2026_06_17     Completed   [Open] │  │
│  │ 12 candidates · 3 confirmed · 9 pending           │  │
│  └──────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Batch: received_2026_06_15     Running  ●  [View] │  │
│  │ Processing... extracting text (stage 3/6)         │  │
│  └──────────────────────────────────────────────────┘  │
│                                                         │
│  [+ Upload new batch]                                   │
└─────────────────────────────────────────────────────────┘
```

Changes needed:
- `/api/jobs` already returns the in-memory job list
- Add a job card component in `app.js`
- Add an "open" action that calls `POST /api/run/select` (new endpoint, or reuse `POST /api/run/clear` + re-upload pattern)
- Note: job list is in-memory only — clears on server restart. For pilot, this is acceptable.

---

## Screen 2: Review queue page (priority: HIGH)

The main review screen after a batch completes.

Current design shows all candidates in a single list. Pilot needs clear queue buckets.

Proposed layout:

```
┌─────────────────────────────────────────────────────────┐
│  Batch: received_2026_06_17   [Summary] [Export] [Done] │
├──────────────┬──────────────────────────────────────────┤
│ Queue        │                                          │
│              │  ┌──────────────────────────────────┐   │
│ Main (8)  ● │  │ Page 3 vs ERE Page 7              │   │
│ Secondary(4) │  │ Likely duplicate  ·  0.91         │   │
│ Confirmed(3) │  │ [Confirm ✓] [Reject ✗] [Unsure ?] │   │
│ Rejected (2) │  └──────────────────────────────────┘   │
│ Unsure   (1) │  ┌──────────────────────────────────┐   │
│              │  │ Page 5 vs ERE Page 2              │   │
│ [Filters ▼]  │  │ Possible duplicate  ·  0.84       │   │
│              │  │ [Confirm ✓] [Reject ✗] [Unsure ?] │   │
│              │  └──────────────────────────────────┘   │
└──────────────┴──────────────────────────────────────────┘
```

Changes needed:
- Replace raw bucket names (`main_review`, `secondary_review`) with plain labels (`Main`, `Secondary`)
- Add confirmed/rejected/unsure sidebar counts derived from reviewer decisions
- Show reranker-demoted indicator on candidates that were promoted back (or note that calibration queue is hidden)
- Calibration-only candidates are hidden from the review queue — add a note at the bottom: "N candidates hidden by confidence filter"

---

## Screen 3: Side-by-side candidate viewer (priority: HIGH)

Currently working. Needs these additions:

```
┌──────────────────────┬──────────────────────┐
│  Page 3              │  ERE Page 7          │
│  received_001.pdf    │  ere_records_004.pdf │
│  (page 3 of 8)       │  (page 7 of 12)      │
│                      │                      │
│  [page image]        │  [page image]        │
│                      │                      │
├──────────────────────┴──────────────────────┤
│ Confidence: 0.91   Match type: hybrid_vector │
│ Queue: Main review                           │
│ Rationale: high text similarity + embedding  │
├─────────────────────────────────────────────┤
│ [Confirm duplicate] [Not a duplicate] [Partial overlap] [Unsure] │
│ Note: ________________                       │
└─────────────────────────────────────────────┘
```

Changes needed:
- Already mostly there. Need to surface `review_rationale` in plain language
- Replace raw `match_type` values with readable strings
- Add "Note" field (already in the data model, not yet exposed in UI)

---

## Screen 4: Batch summary / export (priority: MEDIUM)

After review, the reviewer needs a summary and export.

```
┌─────────────────────────────────────────────┐
│ Batch summary: received_2026_06_17          │
│                                             │
│ Candidates reviewed: 14 / 14               │
│ Confirmed duplicates: 5                     │
│ Rejected: 6                                 │
│ Partial overlap: 1                          │
│ Unsure: 2                                   │
│                                             │
│ Engine stats:                               │
│   Candidates generated: 18                  │
│   Hidden by reranker: 4 (demoted)           │
│   Hidden by confidence floor: 0             │
│                                             │
│ [Download JSON] [Download CSV] [Print view] │
└─────────────────────────────────────────────┘
```

Changes needed:
- Add a summary endpoint or derive from `/api/run` + `/api/review-decisions`
- Export endpoints already exist — just need a visible button

---

## Post-pilot backlog (do not block on these)

```text
Keyboard shortcuts (j/k navigation, d=duplicate, r=reject, u=unsure)
Reviewer name field
Second-review / sign-off workflow
Bulk-action buttons (confirm all main-review)
Search within a batch
Inline text evidence toggle
Confidence explanation overlay
Better progress bar during processing
Mobile/tablet layout
```

---

## Engineering notes

- The current frontend is vanilla JS with no build step (`app.js`, ~800 lines)
- State is managed in a global `state` object
- Adding a job list screen requires persisting jobs across server restarts OR accepting that the list resets (acceptable for pilot)
- The `POST /api/jobs` upload endpoint already exists; job cards can be wired to `GET /api/jobs`
- Plain-language bucket labels are a display-only change — no backend changes needed
- The reranker demotion count is available in the run metrics via `embedding_reranker` summary key
