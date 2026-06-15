# v0.10.9 Semantic Precision Reranker Spec

## Status

Phases 1–3 complete. Phase 4 approved — proceeding to runtime wiring.

See **Phase 3 grid verdict** below for the approved Phase 4 setting.

Do **not** wire this into full `eval-all`, calibration harness, or server calibration runs until the offline simulator proves a safe threshold/action.

## Branch

Start from clean `main`, not from the archived embedding-guard experiment branch.

```bash
git checkout main
git pull --ff-only origin main
git checkout -b feature/v0.10.9-semantic-reranker
```

The archived branch remains reference-only:

```text
experiment/v0.10.9-embedding-guard
```

Do not merge it.

---

# 1. Context

## v0.10.8 baseline

v0.10.8 is the current recall champion.

### v3 widened profile

```text
TP: 135
FN: 27
recall: 0.8333
expected_negative_hit_count: 72
partial_overlap_hit_count: 17
unknown_prediction_count: 9120
candidate rows: 9344
```

### v4 widened profile

```text
TP: 101
FN: 15
recall: 0.8707
expected_negative_hit_count: 0
partial_overlap_hit_count: 17
unknown_prediction_count: 7986
candidate rows: 8104
```

## Problem

The widened embedding profile rescues real duplicates, but on v3 it also admits too many known-negative semantic matches.

Previous v0.10.9 experiments showed that simple embedding caps and threshold sweeps are not enough:

```text
no embeddings:
  v3 recall: 0.6296
  expected negatives: 18

tight embeddings:
  v3 recall: 0.7778
  expected negatives: 38

wide embeddings:
  v3 recall: 0.8333
  expected negatives: 72
```

So embeddings are necessary for recall, but pure semantic/vector candidates need calibrated precision handling.

---

# 2. Diagnostic Findings

The v0.10.9 embedding diagnostic compared pure embedding true positives against pure embedding known negatives from the v0.10.8 widened run.

## v3 pure embedding cohort

```text
pure embedding true positives: 33
pure embedding known negatives: 54
```

The original idea of a hard “supporting deterministic evidence” gate is not viable.

Both TP and KN groups have effectively no support from:

```text
key-token signals: 0
rare-token signals: 0
perceptual hash support: 0
matched deterministic passes: 0
```

These are genuinely blind semantic/vector candidates.

## Separating features

| Feature                   |    TP |    KN | Interpretation                                               |
| ------------------------- | ----: | ----: | ------------------------------------------------------------ |
| embedding similarity mean | 0.907 | 0.852 | Primary useful lever                                         |
| same_document             |   36% |    4% | Same-document semantic hits are much more likely to be real  |
| a_openai_ocr_selected     |   15% |   59% | Heavy OpenAI OCR dependency correlates with false positives  |
| a_tesseract_usable        |   64% |   31% | Better local OCR/text quality correlates with true positives |
| a_best_word_count         |  45.8 |  58.4 | Word count alone does not help; KNs have more text           |

## v4 pure embedding cohort

```text
pure embedding true positives: 49
pure embedding known negatives: 0
```

v4 has no pure embedding precision problem, so the reranker must avoid damaging v4 recall.

---

# 3. Goal

Build a calibrated precision reranker for pure embedding candidates.

The reranker should reduce v3 known-negative semantic hits while preserving recall.

## Success targets

Offline simulation must show:

### v3

```text
TP demotion/drop rate <= 10%
known-negative reduction materially below 72
recall projection remains >= 0.80
```

### v4

```text
TP demotion/drop rate <= 5%
ideally 0%
no new known-negative issue
```

### Runtime behavior

```text
Disabled config = exact pass-through
Non-semantic candidates untouched
All reranker actions traceable
No full calibration run until simulator checkpoint passes
```

---

# 4. Scope

Implement **Phases 1–3 only**.

## In scope now

```text
Phase 1: Reranker module
Phase 2: Unit/integration tests
Phase 3: Offline simulator CLI
```

## Out of scope until checkpoint

```text
Phase 4: eval-all integration
Phase 4: CLI flags
Phase 4: calibration harness integration
Phase 4: reporting integration
Phase 4: full server calibration run
```

---

# 5. Phase 1 — Reranker Module

## Files

Create:

```text
src/dupe_engine/embedding_reranker.py
```

Edit:

```text
src/dupe_engine/config.py
```

## EngineConfig fields

Add the following fields to `EngineConfig`.

All must be default-safe and off-by-default.

```python
embedding_reranker_enabled: bool = False
embedding_reranker_min_confidence: float = 0.88
embedding_reranker_ocr_penalty: float = 0.05
embedding_reranker_same_doc_bonus: float = 0.03
embedding_reranker_tesseract_bonus: float = 0.02
embedding_reranker_action: str = "demote"  # "demote" | "drop"
```

Also add env parsing in config loading if the project already maps similar `EngineConfig` fields from env.

Suggested env names:

```text
DUPE_EMBEDDING_RERANKER_ENABLED
DUPE_EMBEDDING_RERANKER_MIN_CONFIDENCE
DUPE_EMBEDDING_RERANKER_OCR_PENALTY
DUPE_EMBEDDING_RERANKER_SAME_DOC_BONUS
DUPE_EMBEDDING_RERANKER_TESSERACT_BONUS
DUPE_EMBEDDING_RERANKER_ACTION
```

Validate `embedding_reranker_action` defensively:

```text
allowed: "demote", "drop"
fallback/default: "demote"
```

## Target candidate scope

The reranker applies only to pure semantic/vector recall candidates.

Primary condition:

```python
match.match_type == "embedding_similarity_candidate"
```

And if available:

```python
candidate_category == "semantic_recall"
```

Runtime `PageMatch` may not always have `candidate_category` before annotation, so implementation should be robust:

```text
If match_type is not embedding_similarity_candidate:
  untouched

If match_type is embedding_similarity_candidate:
  eligible for reranker
```

The offline simulator can use CSV `candidate_category == semantic_recall`.

## Required data model

Create a dataclass:

```python
@dataclass(frozen=True)
class RerankerParams:
    min_confidence: float
    ocr_penalty: float
    same_doc_bonus: float
    tesseract_bonus: float
    action: str
```

Create another dataclass:

```python
@dataclass(frozen=True)
class RerankerDecision:
    original_confidence: float
    precision_score: float
    decision: str  # "keep" | "demote" | "drop"
    components: dict[str, Any]
    reason: str
```

## Key functions

### `params_from_config(config) -> RerankerParams`

Extracts the relevant config fields.

Defensive behavior:

```text
missing field -> default
invalid action -> demote
```

### `is_pure_embedding_match(match: PageMatch) -> bool`

Returns true for pure embedding candidates.

Minimum implementation:

```python
return match.match_type == "embedding_similarity_candidate"
```

### `score_components(...) -> tuple[float, dict[str, Any]]`

Pure math helper shared by runtime and simulator.

Signature:

```python
def score_components(
    *,
    confidence: float,
    a_ocr: bool,
    b_ocr: bool,
    a_tesseract: bool,
    b_tesseract: bool,
    same_doc: bool,
    params: RerankerParams,
) -> tuple[float, dict[str, Any]]:
    ...
```

Score logic:

```text
score = confidence
score -= ocr_penalty for each OpenAI-OCR-selected page
score += tesseract_bonus for each Tesseract-usable page
score += same_doc_bonus if both pages have the same document_name
```

Return both the final score and a component breakdown.

Example component dict:

```python
{
    "base_confidence": 0.87,
    "a_openai_ocr_selected": True,
    "b_openai_ocr_selected": False,
    "ocr_penalty_total": 0.05,
    "a_tesseract_usable": True,
    "b_tesseract_usable": False,
    "tesseract_bonus_total": 0.02,
    "same_document": False,
    "same_document_bonus": 0.0,
    "precision_score": 0.84,
    "min_confidence": 0.88,
}
```

### `compute_precision_score(match: PageMatch, config: EngineConfig) -> RerankerDecision`

Extracts runtime fields:

```text
confidence: match.confidence
a_ocr: match.page_a.openai_ocr_selected
b_ocr: match.page_b.openai_ocr_selected
a_tesseract: match.page_a.tesseract_usable
b_tesseract: match.page_b.tesseract_usable
same_doc: match.page_a.document_name == match.page_b.document_name
```

Decision rule:

```text
if precision_score >= min_confidence:
    keep
else:
    action from config: demote or drop
```

Reason examples:

```text
embedding_reranker_keep:score_gte_threshold
embedding_reranker_demote:score_lt_threshold
embedding_reranker_drop:score_lt_threshold
```

### `apply_embedding_reranker(matches: list[PageMatch], config: EngineConfig) -> list[PageMatch]`

Behavior:

```text
If disabled:
  return the original matches list unchanged

For each match:
  if not pure embedding:
    keep untouched

  else:
    compute decision

    if keep:
      append ai_route_event
      keep match

    if demote:
      lower confidence below normal review threshold
      set review_rationale to reranker reason
      append ai_route_event
      keep match

    if drop:
      append/drop event if possible
      exclude from returned matches
```

### Demotion behavior

Demotion must be traceable and must route through existing visibility machinery.

Suggested behavior:

```text
match.confidence = min(match.confidence, config.review_threshold - 0.001)
match.review_rationale = "embedding_reranker_demoted: precision_score=<score> < threshold=<threshold>"
```

If `config.review_threshold` does not exist, use a conservative explicit demotion confidence:

```text
0.49
```

Avoid deleting audit data. Demotion should keep the match in artifacts but mark it below normal review priority.

Important risk:

```text
If truth_eval still counts demoted/calibration-only rows as hits, demotion may not reduce expected_negative_hit_count.
```

That is why the simulator must model both drop and demote semantics separately.

### Drop behavior

Drop means candidate is excluded from the returned match list.

This should only happen when:

```text
embedding_reranker_action == "drop"
```

Default is not drop.

### Traceability event

Every reranked pure embedding candidate should get an `ai_route_event` or equivalent metadata event.

Use the project’s existing event shape if available.

Minimum event payload:

```python
{
    "route": "embedding_reranker",
    "decision": "keep" | "demote" | "drop",
    "reason": "...",
    "original_confidence": ...,
    "precision_score": ...,
    "components": {...},
}
```

If dropped candidates cannot be returned, at least make `summarize_reranker()` work on kept/demoted matches. The simulator will handle dropped counts offline.

### `summarize_reranker(matches: list[PageMatch]) -> dict[str, Any]`

Reads `ai_route_events`.

Return:

```python
{
    "enabled": True,
    "evaluated": 0,
    "kept": 0,
    "demoted": 0,
    "dropped": 0,
    "min_precision_score": None,
    "max_precision_score": None,
    "mean_precision_score": None,
}
```

No second state store. Summary should be derivable from match events.

---

# 6. Phase 2 — Tests

## File

Create:

```text
tests/test_embedding_reranker.py
```

Use real project objects where possible:

```text
PageRecord
PageMatch
EngineConfig
```

Tests must not require network, OCR, OpenAI, Docker, or external data.

## Test helper

Create helpers in the test file:

```python
def make_page(
    *,
    document_name="doc.pdf",
    page_number=1,
    openai_ocr_selected=False,
    tesseract_usable=False,
    best_word_count=40,
) -> PageRecord:
    ...
```

```python
def make_embedding_match(
    *,
    confidence=0.90,
    same_doc=False,
    a_ocr=False,
    b_ocr=False,
    a_tess=False,
    b_tess=False,
) -> PageMatch:
    ...
```

## Required test cases

### 1. High confidence same-document keeps

```text
conf = 0.92
same_doc = True
no OCR dependency
expected: keep
```

### 2. High confidence cross-document keeps

```text
conf = 0.91
same_doc = False
no OCR dependency
expected: keep
```

### 3. Low confidence OCR-dependent demotes

```text
conf = 0.85
a_ocr = True
expected: demote
```

### 4. Double OCR penalty demotes

```text
conf = 0.87
a_ocr = True
b_ocr = True
expected: demote
```

### 5. Same-document bonus rescues borderline

```text
conf = 0.86
same_doc = True
with same_doc_bonus = 0.03
min_confidence = 0.88
score = 0.89
expected: keep
```

### 6. Non-pure candidates untouched

```text
match_type = multi_signal_candidate or exact_text_duplicate
expected: same object / no confidence change / no reranker event
```

### 7. Disabled config pass-through

```text
embedding_reranker_enabled = False
expected: returned list is same list or same objects
no events
no score changes
```

### 8. Drop action removes row

```text
embedding_reranker_enabled = True
embedding_reranker_action = "drop"
low score
expected: output excludes match
```

### 9. Demoted match has trace event

Expected event fields:

```text
route = embedding_reranker
decision = demote
components includes base_confidence, precision_score, threshold/min_confidence
```

### 10. Demoted match survives annotation guard

If project has `build_calibration_report` or visibility annotation logic available in tests:

```text
demoted match should retain reranker review_rationale
visibility should become calibration_only or equivalent low-review visibility
calibration annotation should not overwrite reranker rationale
```

If this is too coupled, test the minimum safe behavior:

```text
demoted match confidence is below review threshold
review_rationale starts with embedding_reranker_demoted
```

## Coverage target

```text
>= 80% on src/dupe_engine/embedding_reranker.py
```

## Test command

```bash
pytest tests/test_embedding_reranker.py
pytest
```

---

# 7. Phase 3 — Offline Simulation

## Files

Create:

```text
src/dupe_engine/reranker_sim.py
tools/v0109_reranker_sim.py
```

The simulator must import and reuse:

```text
score_components
RerankerParams
```

from:

```text
src/dupe_engine/embedding_reranker.py
```

No duplicated scoring math.

The simulator may reuse helper functions from:

```text
src/dupe_engine/embedding_diagnostic.py
```

including signal parsing and row enrichment.

## CLI

Command:

```bash
python tools/v0109_reranker_sim.py /path/to/candidate_summary.csv
```

Options:

```text
--out-dir PATH
--min-confidence FLOAT
--ocr-penalty FLOAT
--same-doc-bonus FLOAT
--tesseract-bonus FLOAT
--action demote|drop
--threshold-start FLOAT
--threshold-end FLOAT
--threshold-step FLOAT
```

Defaults:

```text
out-dir: sibling directory or current working directory / reranker_sim_out
min-confidence: 0.88
ocr-penalty: 0.05
same-doc-bonus: 0.03
tesseract-bonus: 0.02
action: demote
threshold-start: 0.80
threshold-end: 0.94
threshold-step: 0.02
```

## Inputs

Input is `candidate_summary.csv`.

Rows may include:

```text
truth_label
match_type
candidate_category
confidence
signals
deterministic_passes
a_document
b_document
a_page
b_page
a_text_source
b_text_source
a_best_word_count
b_best_word_count
a_openai_ocr_selected
b_openai_ocr_selected
a_tesseract_usable
b_tesseract_usable
review_bucket
visibility
```

Missing boolean fields should default to `False`, with warning counts.

Example:

```python
_as_bool(value, default=False)
```

Missing numeric fields should default safely.

## Pure embedding row filter

For CSV simulation:

```python
row["match_type"] == "embedding_similarity_candidate"
```

Optionally require:

```python
row["candidate_category"] == "semantic_recall"
```

But be robust if `candidate_category` is missing.

## Cohorts

Track at least:

```text
duplicate / TP
not_duplicate / known negative
partial_overlap
unlabeled
```

Use exact labels:

```text
truth_label == duplicate
truth_label == not_duplicate
truth_label == partial_overlap
else unlabeled
```

## Row scoring

For each pure embedding row:

```text
confidence = float(row["confidence"])
a_ocr = bool(row["a_openai_ocr_selected"])
b_ocr = bool(row["b_openai_ocr_selected"])
a_tess = bool(row["a_tesseract_usable"])
b_tess = bool(row["b_tesseract_usable"])
same_doc = row["a_document"] == row["b_document"]
```

Use `score_components(...)`.

## Simulation semantics

The simulator must report both action modes:

### Drop semantics

Dropped rows are removed from candidate hits.

This affects projected:

```text
TP kept
TP dropped
KN kept
KN dropped
partial kept/dropped
unlabeled kept/dropped
```

### Demote semantics

Demoted rows remain in artifacts but become low-priority / calibration-only.

The simulator must explicitly report two interpretations:

```text
review-visible impact:
  demoted rows no longer appear in normal review queue

truth-eval impact:
  if evaluator still counts demoted rows, known-negative hit count may not improve
```

This is important. The simulator should not pretend demotion reduces `expected_negative_hit_count` unless the current evaluator semantics actually exclude demoted/calibration-only candidates.

Include this warning in the Markdown output.

## Threshold sweep

Sweep threshold values:

```text
0.80, 0.82, 0.84, 0.86, 0.88, 0.90, 0.92, 0.94
```

Or from CLI params.

For each threshold, report:

```text
threshold
tp_total
tp_kept
tp_demoted_or_dropped
tp_action_rate
kn_total
kn_kept
kn_demoted_or_dropped
kn_action_rate
partial_total
partial_kept
unlabeled_total
unlabeled_kept
estimated_review_rows_removed
```

Also report:

```text
v3/v4 candidate total if known
pure embedding row count
non-pure row count
```

## Recommendation algorithm

Pick the threshold that:

```text
maximizes known-negative action rate
while TP action rate <= 10%
```

Tie-breakers:

```text
1. higher KN removed/actioned
2. lower TP action rate
3. lower unlabeled kept
4. lower threshold if tied, to preserve recall
```

For v4, recommendation should prioritize:

```text
TP action rate <= 5%
ideally 0%
```

The CLI only sees one CSV at a time, so it should report per-file recommendations. Human will compare v3 and v4.

## Outputs

Write:

```text
reranker_sim.md
reranker_sim.json
reranker_sim_sweep.csv
reranker_sim_rows.csv
```

### `reranker_sim.md`

Human-readable summary.

Must include:

```text
input path
parameters
pure embedding cohort counts
recommendation
threshold sweep table
drop-semantics summary
demote-semantics warning
top examples of actioned TP rows
top examples of actioned KN rows
```

### `reranker_sim.json`

Structured equivalent.

### `reranker_sim_sweep.csv`

One row per threshold.

### `reranker_sim_rows.csv`

Enriched row-level output with:

```text
original row identifiers
truth_label
confidence
precision_score
decision at selected threshold
score components
```

---

# 8. Phase 3 Checkpoint Output

After implementing Phases 1–3, run:

```bash
pytest tests/test_embedding_reranker.py
pytest
```

Then run the simulator on v3 and v4 candidate summaries:

```bash
python tools/v0109_reranker_sim.py artifacts/calibration/v0108/v3_candidate_summary.csv --out-dir artifacts/calibration/v0109/reranker_sim_v3

python tools/v0109_reranker_sim.py artifacts/calibration/v0108/v4_candidate_summary.csv --out-dir artifacts/calibration/v0109/reranker_sim_v4
```

Paste the following checkpoint summary:

```text
Tests:
- total tests passing
- new reranker tests passing

v3 recommendation:
- threshold
- action
- TP total
- TP actioned
- TP action rate
- KN total
- KN actioned
- KN action rate
- projected recall if drop semantics
- expected review reduction if demote semantics

v4 recommendation:
- threshold
- action
- TP total
- TP actioned
- TP action rate
- KN total
- KN actioned
- KN action rate
- projected recall if drop semantics

Decision:
- proceed to Phase 4?
- if yes, with demote or drop?
```

Stop here.

Do not implement Phase 4 until this checkpoint is reviewed.

---

---

# Phase 3 grid verdict

The cross-corpus simulator found that a cheap rules-based reranker can reduce v3 pure-embedding known negatives without damaging v4 recall.

Selected Phase 4 setting:

- min confidence / threshold: 0.80
- OCR penalty: 0.01
- same-document bonus: 0.03
- Tesseract bonus: 0.02
- action: demote

Results:

| Corpus | TP action rate | KN action rate | Notes |
|---|---:|---:|---|
| v3 | 3.0% | 16.7% | 1/33 TP touched, 9/54 KN demoted |
| v4 | 2.0% | n/a | 1/49 TP touched, 0 KNs present |

Stretch option:

- OCR penalty 0.02, threshold 0.80
- v3 KN action rate improves to 22.2%
- v4 TP action rate rises to 4.1%

Decision:

Proceed to Phase 4 with the safer setting: `ocr_penalty=0.01`, `threshold=0.80`, `action=demote`.

---

# 9. Phase 4 — Runtime Integration

## Files likely to change

```text
src/dupe_engine/engine.py
src/dupe_engine/cli.py
src/dupe_engine/calibration_harness.py
src/dupe_engine/reporting.py
```

## Runtime insertion point

Insert:

```python
apply_embedding_reranker(matches, config)
```

after embedding candidates have been added and before final review visibility/budget annotation.

Important: insertion point must ensure demoted candidates get correctly routed by existing visibility machinery.

Likely spots:

```text
run_all_pairs_compare
run_ab_compare
```

Need to inspect actual engine flow before patching.

## CLI flags

Future `eval-all` flags:

```text
--embedding-reranker
--embedding-reranker-min-confidence FLOAT
--embedding-reranker-ocr-penalty FLOAT
--embedding-reranker-same-doc-bonus FLOAT
--embedding-reranker-tesseract-bonus FLOAT
--embedding-reranker-action demote|drop
```

## Calibration harness

Add to `CalibrationRunSpec`:

```text
embedding_reranker_enabled
embedding_reranker_min_confidence
embedding_reranker_ocr_penalty
embedding_reranker_same_doc_bonus
embedding_reranker_tesseract_bonus
embedding_reranker_action
```

Emit flags in command builder.

Add scorecard columns.

## Reporting

Surface reranker summary:

```text
embedding_reranker:
  enabled
  evaluated
  kept
  demoted
  dropped
  min_precision_score
  max_precision_score
  mean_precision_score
```

No engine return-type change unless unavoidable.

---

# 10. Commit Plan

After Phase 1–3 implementation and passing tests:

```bash
git status --short
git add src/dupe_engine/embedding_reranker.py src/dupe_engine/reranker_sim.py tools/v0109_reranker_sim.py tests/test_embedding_reranker.py src/dupe_engine/config.py docs/V0_10_9_SEMANTIC_RERANKER_PLAN.md
git commit -m "Add v0.10.9 pure embedding reranker simulation"
git push -u origin feature/v0.10.9-semantic-reranker
```

If implementation is split:

```text
commit 1: Add reranker scoring module and tests
commit 2: Add reranker simulation CLI
commit 3: Update v0.10.9 plan with simulation workflow
```

---

# 11. Non-goals

Do not do these in Phases 1–3:

```text
Do not run full server calibration.
Do not wire reranker into eval-all.
Do not alter default behavior.
Do not merge archived experiment/v0.10.9-embedding-guard branch.
Do not remove embedding candidates globally.
Do not add LLM adjudication yet.
Do not introduce non-stdlib dependencies for the simulator.
```

---

# 12. Implementation Principle

The reranker is not trying to prove duplicates.

It is trying to identify pure semantic candidates that are too risky to treat as normal review-visible duplicate candidates.

Keep the recall layer.

Add precision routing.

Simulate first.

Only calibrate after the simulation demonstrates a safe tradeoff.
