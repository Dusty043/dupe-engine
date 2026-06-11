# v0.10.7 handoff — server continuous calibration and observability

## Summary

v0.10.7 is an operations/harness release. It keeps the duplicate-detection engine behavior intact and adds the server batch-worker layer needed for unattended calibration.

## Motivation

The v0.10.6 p10 emergency run completed cleanly but plateaued around `.62` generalized strict recall. More broad p10 loops are unlikely to reach `.80` by brute force. The next useful step is to make the calibration process visible, bounded, prune-safe, and server-ready.

## New capabilities

- `continuous-calibration` command for server operation.
- p6 sustained default for server runs.
- Guardrails for runtime, storage, API usage, quality/noise, and plateau detection.
- Root-level `run_summary.json` and `run_summary.md`.
- `decision_log.jsonl` for planner/stop decisions after each iteration.
- `timing.jsonl` and `errors.jsonl` for operational observability.
- Root-level aggregate `scorecard.json` / `scorecard.csv`.
- Root-level `best_config.json` / `best_config.md`.
- `prune-calibration-run` command.
- `--prune-artifacts analysis-only` mode after each completed iteration.
- Dockerfile, docker-compose.yml, and server runner script.

## Important commands

Dry-run server plan:

```bash
PYTHONPATH=src python -m dupe_engine.cli continuous-calibration \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0106_emergency_p10 \
  --out-dir ./output/calibration/loop_v0107_dry_run \
  --target-recall 0.80 \
  --dry-run
```

Live p6 server-style run:

```bash
PYTHONPATH=src python -m dupe_engine.cli continuous-calibration \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0106_emergency_p10 \
  --out-dir ./output/calibration/loop_v0107_server_p6 \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 6 \
  --parallel-hard-cap 10 \
  --max-total-runtime-hours 24 \
  --max-iteration-runtime-hours 3 \
  --max-run-dir-gb 25 \
  --min-free-disk-gb 40 \
  --max-openai-ocr-pages 10000 \
  --max-embedding-calls 50000 \
  --max-llm-analysis-calls 50 \
  --max-best-unknown-predictions 15000 \
  --max-best-known-negative-hits 50 \
  --max-plateau-iterations 3 \
  --min-recall-gain 0.01 \
  --aggressive-search \
  --prune-artifacts analysis-only \
  --progress tui \
  --confirm-live-ai
```

Prune an existing run:

```bash
PYTHONPATH=src python -m dupe_engine.cli prune-calibration-run ./output/calibration/loop_v0107_server_p6 --mode analysis-only --apply
```

## Docker

Use Docker to make the worker runtime disposable, not the data.

```text
container/image = disposable runtime
/srv/data/dupe-engine = persistent corpora/truth/runs/logs/cache
```

Server smoke:

```bash
docker compose build
docker compose run --rm dupe-worker dupe-engine doctor
```

Live server script:

```bash
docker compose run --rm dupe-worker ./scripts/run_server_continuous_v0107.sh
```

## Validation

Unit tests added for pruning, guardrails, and observability logs.

Run:

```bash
PYTHONPATH=src pytest -q
```
