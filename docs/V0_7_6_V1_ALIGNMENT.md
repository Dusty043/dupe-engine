# v0.7.6 V1 Alignment Notes

v0.7.6 is the bridge from calibration output to the v1 reviewer contract.

## Product stance carried forward

The engine is still a human-review assist tool. It should surface a reviewable candidate set with reasons. It should not delete, merge, or silently suppress evidence that a reviewer or calibration run may need later.

## Label contract

Engine candidate labels are restricted to:

```text
duplicate
likely_duplicate
possible_duplicate
partial_overlap
needs_review
```

Future adjudicator and human labels may also include:

```text
not_duplicate
```

`low_information_ignore` is not a candidate label. It is a truth/evaluation bucket used by synthetic data and calibration reports.

## Separation of concerns

### Detector evidence

Stored in:

```text
match_type
signals
deterministic_passes
confidence
candidate_stage
```

### Engine reviewer label

Stored in:

```text
engine_candidate_label
review_bucket
```

`review_bucket` is retained for compatibility and mirrors `engine_candidate_label`.

### Queue visibility

Stored in:

```text
visibility
visibility_reason
candidate_category
```

Values:

```text
main_review_list
low_information
calibration_only
```

### Future adjudicator and human decisions

Stored as empty placeholders until those layers exist:

```text
adjudicator_suggested_label
human_final_label
```

## Visibility rules

### Main review list

Use for exact, strict, standard, or above-threshold non-low-information candidates.

### Low-information

Use when either page is marked low-information. These pairs should not pollute the default reviewer list. If retained, they should appear in a separate section.

### Calibration only

Use for loose/borderline candidates that are helpful for threshold tuning but too noisy for the default Sorter/Organizer queue.

Also use for candidates that would otherwise exceed the default main review workload budget:

```text
50 main-list candidates per 100 pages
```

This budget only changes queue visibility. It does not delete detector candidates from JSON/CSV calibration output.

## Calibration metrics added

v0.7.6 calibration outputs include raw candidate load and default reviewer load separately:

```text
candidate_count
candidate_pairs_per_100_pages
main_review_list_candidate_count
main_review_list_pairs_per_100_pages
low_information_candidate_count
calibration_only_candidate_count
```

This lets the project tune toward the v1 workload target without throwing away diagnostic candidates too early.
