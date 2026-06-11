# v0.10.8 Next Experiment Plan

## Current read

The server characterization phase is done enough for now.

Recommended sustained server mode:

```text
p4
```

Avoid:

```text
p6 as default
p10 on this server
broad aggressive sweeps without targeted provenance
```

## First command after applying v0.10.8

Run diagnostics against the completed p4 rerun:

```bash
cd /srv/apps/dupe-engine/dupe_engine_v0_10_8_project

docker compose run --rm dupe-worker python tools/v0108_calibration_diagnostics.py \
  /data/runs/loop_v0107_server_p4_rerun1 \
  --out-dir /data/runs/loop_v0107_server_p4_rerun1/v0108_diagnostics
```

Then inspect:

```bash
cat /srv/data/dupe-engine/runs/loop_v0107_server_p4_rerun1/v0108_diagnostics/v0108_diagnostics.md
```

## What to look for

### 1. Champion source

If the global best source is:

```text
inherited_or_bootstrap
```

then the current run did not produce a new champion, even if the global best is still shown in the summary.

### 2. Current-run best

Use the current-run best as the comparator for the next targeted experiment.

### 3. Dominant false-negative bucket

If the dominant bucket remains:

```text
ocr_or_vision_layer_miss
```

then the next engine patch should not be another vector expansion or broad threshold sweep.

### 4. Split hints

If a logical family has different best members per corpus, consider corpus-aware routing in a future patch.

## Recommended next engine-quality direction

Build a targeted OCR/vision miss rescue path.

The first implementation should add provenance before changing decisions:

- For each false negative, determine whether both pages were OCR-selected.
- If selected, determine whether OCR text was usable.
- If usable, determine whether the candidate pair existed.
- If candidate existed, determine which queue it entered.
- If queued, determine whether confidence/review thresholds suppressed it.

Only after this attribution is reliable should we change scoring or routing.

## Guardrail

Do not call the target missed because p4 failed. p4 succeeded operationally. The quality target failed because the search space plateaued.
