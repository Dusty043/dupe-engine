# Duplicate Checker Pilot Preparation Plan

## Pilot objective

The pilot should prove whether the Duplicate Checker meaningfully reduces manual document comparison work while keeping reviewers in control.

The goal is not to prove that the engine is perfect.

The goal is to prove:

```text
The engine catches useful duplicate candidates.
Reviewers can understand and act on the results.
False positives are manageable.
Misses are visible enough to improve the system.
The workflow saves time compared with the current manual process.
```

## Pilot posture

The system should launch as an assistive review tool.

It should not make final decisions automatically.

Allowed:

```text
suggest duplicate candidates
rank matches by confidence/review bucket
show evidence and rationale
allow reviewers to confirm/reject/mark unsure
export review results
store audit history
```

Not allowed during pilot:

```text
auto-delete documents
auto-merge cases
auto-finalize duplicate decisions
hide uncertain results without audit trail
replace human review
```

## Pilot users

Initial users should be a small review group familiar with the document workflow.

Suggested pilot size:

```text
2–5 reviewers
2–5 historical or low-risk real batches
1 project owner monitoring results
```

## Pilot workflow

### 1. Batch intake

A user uploads or selects a batch of documents.

The system creates a job and shows:

```text
batch name
number of documents
number of pages
job status
started time
processing stage
```

### 2. Processing

The engine runs the duplicate detection pipeline.

The UI should show clear progress states:

```text
queued
rendering documents
extracting text / OCR
finding duplicate candidates
ranking results
completed
failed
```

Failures must be visible and recoverable.

### 3. Review queue

The output should be split into practical review buckets:

```text
Main Review
Secondary Review
Calibration / Low Priority
Dismissed / Not Duplicate
Confirmed Duplicate
Unsure
```

For pilot, reviewers should primarily work from Main Review first, then Secondary Review if time permits.

### 4. Candidate review

Each candidate pair should show:

```text
side-by-side page preview
document names
page numbers
confidence score
match type
review bucket
reason/rationale
OCR/text availability indicator
whether the match was reranked or demoted
```

The reviewer must be able to choose:

```text
Confirm duplicate
Reject / not duplicate
Partial overlap
Unsure / needs second review
Add note
```

### 5. Audit and export

Every reviewer action should be saved.

At minimum, store:

```text
reviewer
timestamp
candidate pair
decision
optional note
previous status
new status
engine confidence
engine rationale
```

Pilot exports should include:

```text
batch summary
confirmed duplicates
rejected candidates
unsure candidates
engine metrics
reviewer decisions
```

## UI improvement requirements

The current UI should be improved before a broader rollout.

For the controlled pilot, the UI does not need to be beautiful, but it must be clear enough that non-technical reviewers can complete the task without needing engine knowledge.

### Critical UI needs before pilot

```text
Job list with status
Job detail page
Clear review buckets
Candidate list with filters
Side-by-side document/page viewer
Confirm/reject/unsure actions
Decision persistence
Basic audit log
Export/download results
Visible job failures
```

### Important but can follow after pilot starts

```text
Keyboard shortcuts
Advanced filtering
Bulk actions
Reviewer assignment
Second-review workflow
Search within batch
Inline OCR/text evidence view
Confidence explanation improvements
Better charts/summary dashboard
```

### UI principle

The UI should not expose raw engine complexity as the main experience.

Reviewers need plain-language labels:

```text
Likely duplicate
Possible duplicate
Needs review
Low-confidence semantic match
Rejected
Confirmed
Unsure
```

Technical details should be available, but secondary.

## Pilot metrics

The pilot should measure both engine quality and workflow usefulness.

### Engine metrics

```text
recall estimate on reviewed batches
false positive rate in main review
false positive rate in secondary review
number of confirmed duplicates found
number of missed duplicates discovered manually
number of uncertain cases
```

### Workflow metrics

```text
time to review a batch
number of candidates reviewed
reviewer agreement rate
reviewer trust rating
number of times reviewer needed engineering help
number of failed or confusing jobs
```

### Product readiness metrics

```text
Can a reviewer complete the workflow without technical support?
Are outputs understandable?
Are false positives annoying but manageable?
Are reports useful to the project owner?
Is audit history sufficient?
```

## Pilot acceptance criteria

The pilot is successful if:

```text
Reviewers can complete review using the UI.
The engine surfaces useful duplicates that would otherwise take manual effort.
False positives do not overwhelm the review process.
All decisions are saved and exportable.
The team can explain every system output through reports/audit logs.
No automatic destructive action occurs.
```

The pilot should not be considered a failure just because false positives exist. The important question is whether the ranked review workflow saves time and improves coverage.

## Pilot risks

| Risk                     | Mitigation                                                                  |
| ------------------------ | --------------------------------------------------------------------------- |
| UI is too confusing      | Keep pilot users small; simplify labels; add basic walkthrough              |
| Too many false positives | Start with Main Review only; use Secondary Review as optional               |
| Missed duplicates        | Keep human review in loop; collect missed examples for calibration          |
| OCR/API variance         | Track run settings and manifests; avoid overpromising exact repeatability   |
| Reviewer distrust        | Show side-by-side evidence and allow easy rejection                         |
| Cost overruns            | Cap OCR/embedding budgets per job and expose usage summaries                |
| Compliance concerns      | Confirm approved infrastructure and data-handling rules before real batches |

## Immediate next work

### Engineering

```text
Merge/tag v0.10.9 if not already merged.
Freeze engine tuning unless real data shows a specific issue.
Prepare pilot deployment path.
Confirm job outputs, manifests, and reports are retained.
Confirm reranker stats appear in reports.
```

### UI

```text
Design the review queue page.
Design the side-by-side candidate review screen.
Add decision buttons and persistence.
Add batch/job status visibility.
Add export/report download.
```

### Operations

```text
Choose pilot batches.
Choose pilot reviewers.
Define review labels.
Define who resolves unsure cases.
Define where exports are stored.
Define how pilot feedback is collected.
```

## Recommended pilot rollout

### Stage 1 — Internal dry run

Use a known synthetic or historical batch.

Goal:

```text
Verify the workflow end to end.
Find UI blockers.
Confirm reports and exports.
```

### Stage 2 — Controlled real batch

Use one low-risk real batch with human review.

Goal:

```text
Measure review usefulness.
Capture false positives and misses.
Validate reviewer workflow.
```

### Stage 3 — Pilot expansion

Run several batches with the same workflow.

Goal:

```text
Confirm consistency across document types.
Decide whether the UI and engine are ready for broader rollout.
```

## Final pilot position

The engine is ready to leave pure calibration.

The next bottleneck is not the duplicate detection core. The next bottleneck is productization:

```text
review UI
decision capture
auditability
exports
real-batch feedback
```

The pilot should proceed once the minimum review UI is in place.
