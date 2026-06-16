# Pilot Review Labels

This document defines the reviewer decision labels for the v1 pilot and explains what each means in plain language.

---

## Reviewer decision labels

These are the labels a reviewer can assign to any candidate pair in the review queue.

| Label | Reviewer says | When to use |
|---|---|---|
| `duplicate` | **Confirmed duplicate** | The pages are clearly the same page. The same content appears in both records. |
| `likely_duplicate` | **Likely duplicate** | Strong match but the reviewer is not 100% certain. Flag for secondary review or accept as duplicate. |
| `not_duplicate` | **Not a duplicate** | The pages are different. The engine was wrong. |
| `partial_overlap` | **Partial overlap** | The pages are related but not identical — one may contain a subset of the other's content. |
| `needs_review` | **Unsure / needs second look** | Reviewer cannot decide. Needs a second reviewer or more context. |

---

## Engine queue buckets (not reviewer decisions)

These are assigned by the engine, not by the reviewer. They determine which review queue a candidate appears in.

| Queue bucket | Meaning |
|---|---|
| `main_review` | High confidence. Review these first. |
| `secondary_review` | Moderate confidence. Review after main queue. |
| `calibration_only` | Low confidence or reranker-demoted. Do not show to reviewers during pilot. |

The embedding reranker (v0.10.9) may demote a candidate from `main_review` or `secondary_review` to `calibration_only` if its precision score falls below the configured threshold. Demoted candidates are still stored in the run for audit purposes.

---

## Pilot label guidance

During the pilot, reviewers should use these labels in plain language:

| What the reviewer sees | Underlying label |
|---|---|
| Confirm duplicate | `duplicate` |
| Reject (not a duplicate) | `not_duplicate` |
| Partial overlap | `partial_overlap` |
| Unsure | `needs_review` |

`likely_duplicate` is available but optional for the pilot. If the UI shows it, reviewers can treat "Likely duplicate" as "Confirm" with a note that confidence was not 100%.

---

## Unreviewed candidates

Candidates that the reviewer has not touched stay at `needs_review` (the engine default assignment). This is intentional: unreviewed items are surfaced in exports as still-pending, not as confirmed negatives.

---

## Label storage

Reviewer decisions are saved in:

```text
<run-dir>/review_decisions.json
```

Each entry stores:

```json
{
  "candidate_id": "...",
  "label": "duplicate",
  "reviewer": "...",
  "timestamp": "...",
  "note": ""
}
```

---

## Open questions for pilot ops

- Who is the tiebreaker for `needs_review` cases that two reviewers disagree on?
- Do `likely_duplicate` decisions auto-confirm, or do they require a second sign-off?
- Should the UI show `partial_overlap` in the main review queue or a separate bucket?
- What happens to `not_duplicate` cases in downstream workflow — are they archived or deleted?
