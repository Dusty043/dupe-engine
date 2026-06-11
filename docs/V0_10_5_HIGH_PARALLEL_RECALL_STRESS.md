# v0.10.5 High-Parallel Recall Stress Testing

v0.10.5 makes the calibration harness more aggressive for urgent recall discovery.

## New CLI knobs

```bash
--max-parallel-runs 10
--parallel-hard-cap 10
--aggressive-search
```

`--max-parallel-runs` controls the number of concurrent engine sub-runs. It is clamped by `--parallel-hard-cap`, which defaults to `10`.

`--aggressive-search` expands the variant planner with wider recall experiments. These experiments are intentionally noisier.

## New stress command

```bash
calibrate-loop-stress --parallel-candidates 10,6
```

This command tries high parallelism first, then falls back if any sub-runs fail.

Output layout:

```text
loop_v0105_stress/
  parallel_stress_summary.json
  p10/
    calibration_loop_state.json
    iteration_01/
  p6/
    calibration_loop_state.json
    iteration_01/
```

The summary file records which worker count was selected.

## Recommended emergency settings

For fast recall discovery:

```bash
--batch-size 5
--max-parallel-runs 10
--max-iterations 6
--aggressive-search
--progress tui
--confirm-live-ai
```

With two corpora, `--batch-size 5` creates `10` sub-runs per iteration, which fully uses `--max-parallel-runs 10`.

## Interpretation

A successful stress result means the machine can complete the run shape without failed/aborted rows. It does not mean the engine reached 0.80 recall.

If recall still plateaus under aggressive search, the blocker is probably not test speed. It is likely candidate routing, adjudication, or a deeper v4-specific failure mode.
