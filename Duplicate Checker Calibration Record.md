# Duplicate Checker Calibration Record

## Status

The duplicate detection engine is now **pilot-ready** for controlled, human-reviewed use.

It is not approved for unsupervised or fully automated duplicate decisions.

## Current version posture

| Version | Status                 | Notes                                                                  |
| ------- | ---------------------- | ---------------------------------------------------------------------- |
| v0.10.8 | Stable recall baseline | Cleared the recall target on both v3 and v4 synthetic calibration sets |
| v0.10.9 | Pilot candidate        | Adds a gated pure-embedding reranker for secondary-review cleanup      |

v0.10.9 should be treated as the current pilot candidate because it preserves recall above the target floor and improves secondary-review routing without demoting labeled true positives in validation.

## Calibration goal

The calibration target was to answer:

> Can the engine find duplicate and near-duplicate document candidates without exploding into unusable false positives?

The main acceptance target was:

```text
Recall >= 0.80 on the main calibration corpora
```

Secondary goals were:

```text
Keep review queues usable
Preserve auditability
Avoid silent candidate loss
Expose routing and reranker behavior in reports
```

## Validated corpora

Validation was performed against synthetic calibration corpora designed to stress:

```text
duplicate pages
near duplicates
partial overlaps
same-template different-content pages
OCR/scanned pages
embedding-only semantic matches
hard negatives
multi-source batch behavior
```

Primary validation sets:

```text
Synthetic v3 medium calibration
Synthetic v4 calibration
```

## Baseline result: v0.10.8

v0.10.8 became the recall champion.

| Metric              | v3     | v4     |
| ------------------- | ------ | ------ |
| Recall              | 0.8333 | 0.8707 |
| True positives      | 135    | 101    |
| False negatives     | 27     | 15     |
| Known-negative hits | 72     | 0      |

Interpretation:

```text
v0.10.8 solved the main recall problem.
v3 still had precision/review-noise pressure.
v4 was already clean from a known-negative perspective.
```

## v0.10.9 reranker purpose

v0.10.9 adds a gated pure-embedding reranker.

The reranker does not replace the detection pipeline. It only routes lower-confidence pure semantic matches away from higher-priority review buckets.

Approved setting:

```text
min_confidence = 0.80
ocr_penalty = 0.01
same_doc_bonus = 0.03
tesseract_bonus = 0.02
action = demote
```

The reranker is gated and should only run when explicitly enabled.

## v0.10.9 validation result

| Metric                           | v0.10.8 v3 baseline | v0.10.9 v3 reranker | v0.10.8 v4 baseline | v0.10.9 v4 reranker |
| -------------------------------- | ------------------- | ------------------- | ------------------- | ------------------- |
| Recall                           | 0.8333              | 0.8272              | 0.8707              | 0.8534              |
| True positives                   | 135                 | 134                 | 101                 | 99                  |
| False negatives                  | 27                  | 28                  | 15                  | 17                  |
| Known-negative hits total        | 72                  | 77                  | 0                   | 0                   |
| Main review list size            | 1,690               | 1,690               | 1,092               | 1,092               |
| Main review known negatives      | 7                   | 7                   | 0                   | 0                   |
| Secondary review known negatives | 54                  | 49                  | 0                   | 0                   |
| Reranker evaluated               | —                   | 3,665               | —                   | 2,143               |
| Reranker demoted                 | —                   | 650                 | —                   | 629                 |
| Reranker demoted true positives  | —                   | 0                   | —                   | 0                   |
| Reranker demoted known negatives | —                   | 10                  | —                   | 0                   |

## Interpretation

v0.10.9 passed the recall floor:

```text
v3 recall: 0.8272
v4 recall: 0.8534
```

The reranker did not demote labeled true positives in the server validation run.

The reranker does not reduce the main review queue because pure embedding candidates were already routed to secondary review by v0.10.8. Its value is therefore:

```text
secondary-review cleanup
semantic-noise reduction
better traceability
safer routing of weaker embedding-only candidates
```

It should not be described as a main-review false-positive reducer.

## Known limitations

The current validation is still calibration-heavy and synthetic-heavy.

The engine is not yet validated against enough real client/historical batches to claim production-grade accuracy on real-world data.

Known limitations:

```text
Main-review known negatives are not solved by v0.10.9.
The UI needs improvement before broader rollout.
Real-data thresholds may differ from synthetic calibration thresholds.
OCR and embedding API behavior can introduce small run-to-run variance.
The engine should remain human-in-the-loop.
```

## Pilot readiness decision

The engine is approved for a controlled pilot under these conditions:

```text
Human review is required.
No automatic deletion, merging, or final duplicate decisions.
All candidate outputs are auditable.
Reviewer decisions must be saved.
Reports must be retained.
The UI must make confidence, routing, and review status understandable.
```

## Current recommendation

Proceed to pilot preparation using:

```text
v0.10.8 as the stable baseline
v0.10.9 reranker enabled as a gated pilot feature
```

The next phase should focus less on engine tuning and more on:

```text
pilot workflow
review UI
audit trail
reviewer feedback capture
real-batch validation
```
