# v0.10.7 server continuous calibration

v0.10.7 does not change the duplicate-detection engine. It changes how long calibration runs are operated on a server.

The goal is to make calibration a visible, bounded batch process:

```text
run continuously toward .80 recall
but stop or pause when runtime, storage, API usage, quality, or plateau guardrails fire
```

## What changed

### New command

```bash
dupe-engine continuous-calibration ...
```

This is a server-oriented wrapper around the existing iterative calibration loop. Defaults are intentionally different from local testing:

```text
max parallel runs: 6
batch size: 3
max iterations: 999
pruning: analysis-only
plateau stop: 3 iterations without >= 0.01 recall gain
```

### New observability artifacts

Each run directory now keeps compact evidence at the root:

```text
run_summary.json
run_summary.md
scorecard.json
scorecard.csv
decision_log.jsonl
timing.jsonl
errors.jsonl
best_config.json
best_config.md
calibration_loop_state.json
```

Each iteration still writes its own summary and scorecard, but completed iterations can be pruned aggressively.

### Decision log

`decision_log.jsonl` records why the runner continued or stopped after each iteration. Each event includes:

```text
iteration
best variant
best/worst recall metrics
recall gain
plateau count
accepted status
guardrail status
next planned variants
human-readable decision summary
```

### Timing log

`timing.jsonl` records loop and iteration timing events:

```text
loop_started
iteration_started
iteration_runs_completed
iteration_pruned
loop_finished
```

### Guardrails

Supported guardrails include:

```text
--max-total-runtime-hours
--max-iteration-runtime-hours
--max-run-dir-gb
--min-free-disk-gb
--max-openai-ocr-pages
--max-embedding-calls
--max-llm-analysis-calls
--max-unknown-predictions-total
--max-known-negative-hits-total
--max-best-unknown-predictions
--max-best-known-negative-hits
--max-plateau-iterations
--min-recall-gain
```

Possible stop statuses include:

```text
accepted
stopped_max_iterations
stopped_plateau
stopped_runtime_limit
stopped_iteration_runtime_limit
paused_storage_limit
paused_cost_limit
stopped_quality_limit
stopped_no_planned_runs
```

### Pruning

Use:

```bash
dupe-engine prune-calibration-run /data/runs/<run> --mode analysis-only --apply
```

or run continuous calibration with:

```bash
--prune-artifacts analysis-only
```

`analysis-only` keeps:

```text
.json
.jsonl
.csv
.md
.txt
```

and deletes bulky intermediate images, copied PDFs, HTML/debug renderings, and raw logs after summary files exist.

The prune command refuses to apply when no summary marker exists unless `--no-summary-required` is passed.

## Server layout

Recommended host layout:

```text
/srv/apps/dupe-engine
/srv/data/dupe-engine/corpora
/srv/data/dupe-engine/truth
/srv/data/dupe-engine/runs
/srv/data/dupe-engine/logs
/srv/data/dupe-engine/cache
```

Inside Docker, these are mounted as:

```text
/app
/data/corpora
/data/truth
/data/runs
/data/logs
/data/cache
```

The container is disposable. `/srv/data/dupe-engine` is not.

## Docker smoke test

Build and run doctor:

```bash
cd /srv/apps/dupe-engine
docker compose build
docker compose run --rm dupe-worker dupe-engine doctor
```

Dry-run the server command:

```bash
docker compose run --rm dupe-worker dupe-engine continuous-calibration \
  /data/corpora/synthetic_v3/medium_calibration \
  --truth /data/truth/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir /data/corpora/synthetic_v4_calibration \
  --secondary-truth /data/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir /data/runs/bootstrap/loop_v0106_emergency_p10 \
  --out-dir /data/runs/loop_v0107_dry_run \
  --target-recall 0.80 \
  --dry-run
```

## Live server command

The packaged script is:

```bash
scripts/run_server_continuous_v0107.sh
```

Host/Docker example:

```bash
docker compose run --rm dupe-worker ./scripts/run_server_continuous_v0107.sh
```

The script uses p6 sustained parallelism and writes to `/data/runs/loop_v0107_server_p6_<timestamp>`.

## Why p6 by default

The p10 emergency run proved the harness can survive high parallelism, but it plateaued near `.62` generalized recall and creates more pressure on CPU, storage, API calls, and logs. p6 is the sustained server default because it is more likely to run unattended without thrashing.

p10 remains useful for smoke/stress checks. p4 remains the fallback if the server is thermally or memory constrained.
