# Dupe Engine v0.10.8 Release Notes

## Release intent

v0.10.8 is an additive diagnostics and observability release on top of v0.10.7.

It does not rewrite the detection engine. The goal is to make the current recall plateau explainable before spending more OCR, embedding, or LLM budget.

## Why this release exists

The p4 server run completed cleanly:

- 12 / 12 planned runs executed
- 3 iterations completed
- stop reason: `stopped_plateau`
- target not accepted: `strict_recall >= 0.80`
- global best still around the existing generalized ceiling

The important operational issue found in v0.10.7 is that the run summary can present a global/bootstrap champion as the best candidate without clearly separating it from newly executed candidates. This makes it too easy to think a new run improved the engine when it may only have retained an inherited champion.

## Added in v0.10.8

### 1. Calibration diagnostics tool

```bash
python tools/v0108_calibration_diagnostics.py /path/to/run_dir
```

Writes:

- `v0108_diagnostics/v0108_diagnostics.md`
- `v0108_diagnostics/v0108_diagnostics.json`
- `v0108_diagnostics/variant_comparison.csv`
- `v0108_diagnostics/family_by_corpus.csv`

### 2. Champion source separation

v0.10.8 classifies the global best as one of:

- `current_run`
- `inherited_or_bootstrap`
- `reused`
- `unknown`

This is based on run IDs, loop indexes, iteration count, and reuse metadata.

### 3. Current-run comparator

The diagnostics report identifies the best newly executed exact variant separately from the global best.

This is the metric that should be used to decide whether the current calibration run actually improved anything.

### 4. Plateau summary

The diagnostics report extracts per-iteration plateau count, best metric gain, best variant, and stop reason from `decision_log.jsonl`.

### 5. Throughput summary

The diagnostics report computes:

- runtime hours
- executed runs from decision log
- runs/hour
- seconds/executed run
- OpenAI OCR attempted/run
- embedding calls/run

This supports p3/p4/p6 comparison without manually reading logs.

### 6. False-negative bottleneck summary

The diagnostics report aggregates false-negative reason buckets and identifies the dominant bucket.

Current known dominant bucket:

```text
ocr_or_vision_layer_miss
```

### 7. Variant family/corpus split hints

The diagnostics report strips loop prefixes and compares logical families across corpora.

This is not an accepted-candidate mechanism. It is a signal for future routing work where v3 and v4 may prefer different members of a strategy family.

## Not included

v0.10.8 intentionally does not:

- change candidate scoring
- change OCR selection
- change fallback selection
- change adjudication behavior
- spend additional API calls by itself
- claim a path to `strict_recall >= 0.80`

## Acceptance criteria

v0.10.8 is accepted if:

1. Existing v0.10.7 tests still pass.
2. `tests/run_v0108_selftest.py` passes.
3. The diagnostics tool runs on `loop_v0107_server_p4_rerun1`.
4. The diagnostics markdown clearly states whether the global champion is current or inherited/bootstrap.
5. Throughput metrics match the p4 operational readout closely enough to compare against p6.

## Recommended next quality patch after v0.10.8

The next engine-quality patch should target:

1. OCR/vision miss rescue
2. Fallback selection rescue
3. Candidate provenance per false negative
4. Corpus-aware routing

Do not run another broad aggressive calibration matrix until those diagnostics are in place.
