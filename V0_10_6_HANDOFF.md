# v0.10.6 Handoff — Nonfatal LLM Analysis for High-Parallel Stress

v0.10.6 is a small harness hardening patch on top of v0.10.5. It does not change engine matching behavior.

## Why this patch exists

The first `calibrate-loop-stress` run reported both `p10` and `p6` as failed while showing `failed_runs=0`. That means the engine sub-runs did not fail; the failure happened at loop level after or around the scorecards, most likely in optional per-iteration LLM analysis.

## Changes

- Per-iteration LLM analysis is now nonfatal by default.
- If LLM analysis fails, the loop writes `llm_analysis.json` and `llm_analysis.md` with `status=failed_nonfatal` and continues.
- Add `--fatal-llm-analysis` for strict debugging.
- `calibrate-loop-stress` now prints `scorecard_row_count` and the loop-level `error_message` for each parallel candidate.

## Recommended stress command

```bash
PYTHONPATH=src python -m dupe_engine.cli calibrate-loop-stress \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0104 \
  --out-dir ./output/calibration/loop_v0106_stress_smoke \
  --target-recall 0.80 \
  --batch-size 5 \
  --max-iterations 1 \
  --parallel-candidates 10,6 \
  --aggressive-search \
  --progress tui \
  --confirm-live-ai
```

Do not use `--fatal-llm-analysis` for long recall searches unless debugging the analysis step itself.
