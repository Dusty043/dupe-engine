# v0.10.4 Parallel Calibration TUI

v0.10.4 upgrades the calibration-loop display before the next long run.

The engine/candidate-generation behavior from v0.10.3 is unchanged. The main change is that two concurrent calibration sub-runs can now use the fancy terminal display safely.

## Why this exists

v0.10.3 supported:

```bash
--max-parallel-runs 2
```

but when paired with:

```bash
--progress tui
```

it downgraded to plain logs. That avoided terminal contention because each child run tried to render its own dashboard.

v0.10.4 changes ownership of the display:

```text
parent calibration loop owns the terminal
child engine runs only write progress.json/progress_events.jsonl
parent reads both active run folders
parent renders one aggregate dashboard
```

So this now works as intended:

```bash
--max-parallel-runs 2 --progress tui
```

## What the aggregate dashboard shows

The dashboard shows:

```text
iteration number
target metric / target recall
active worker count
completed / failed / pending counts
overall batch progress
one row per planned sub-run
per-run corpus / variant / progress / stage
last completed scorecard rows
iteration output folder
```

This is designed for long two-worker Mac runs where you want visual status without opening each run folder.

## Recommended live command

```bash
export DUPE_OPENAI_API_KEY="your_key_here"

PYTHONPATH=src python -m dupe_engine.cli calibrate-loop \
  ./examples/synthetic_v3/medium_calibration \
  --truth ./examples/synthetic_v3/medium_calibration/synthetic_v3_truth_pairs.json \
  --secondary-pdf-dir ./examples/synthetic_v4_calibration \
  --secondary-truth ./examples/synthetic_v4_calibration/truth/synthetic_v4_calibration_truth_pairs.json \
  --corpus-id v3_medium \
  --secondary-corpus-id v4_calibration \
  --bootstrap-calibration-dir ./output/calibration/loop_v0102 \
  --out-dir ./output/calibration/loop_v0104 \
  --target-recall 0.80 \
  --batch-size 3 \
  --max-parallel-runs 2 \
  --max-iterations 4 \
  --progress tui \
  --confirm-live-ai
```

Do not include this flag for real LLM analysis:

```bash
--llm-analysis-dry-run
```

## Log-friendly alternative

Use plain mode if you are redirecting output to a file or running inside a terminal that does not handle cursor control well:

```bash
--progress plain
```

## Safety boundaries

The workstation concurrency cap is still enforced:

```text
requested workers > 2 => normalized to 2
```

v0.10.4 does not make OCR, embeddings, or LLM calls more aggressive. It only improves how the parallel loop is displayed.

## Validation

The v0.10.4 test coverage includes:

```text
parallel aggregate dashboard smoke test
parallel calibrate-loop parent renderer test
existing calibrate-loop dry-run tests
existing benchmark TUI tests
full regression suite
```
