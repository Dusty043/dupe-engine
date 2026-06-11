# v0.5 Candidate Hygiene

Synthetic v2 showed candidate explosion and low-information false positives. v0.5 introduced controls before embeddings/LLMs are used.

## Low-information pages

Pages may be marked low-information when they are blank, separator, generic cover sheets, signature-only pages, or very low word-count pages.

The engine does not delete or modify these pages. It only suppresses/downranks candidate pairs so reviewers are not flooded with useless matches.

## Candidate budgets

Budgets are applied after candidate aggregation:

```text
max candidates per job
max candidates per page
```

This preserves high-recall detection while keeping output reviewable.

## Defaults

```text
low_information_filter: enabled
suppress_low_information_candidates: true
include_low_information_exact_matches: false
max_candidates_per_job: 2000
max_candidates_per_page: 40
```
