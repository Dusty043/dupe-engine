#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${1:-}"
MODE="${2:---dry-run}"

if [ -z "$RUN_DIR" ]; then
  echo "Usage: $0 /srv/data/dupe-engine/runs/<run> --dry-run|--apply"
  exit 1
fi

case "$MODE" in
  --dry-run) APPLY="" ;;
  --apply) APPLY="--apply" ;;
  *) echo "Mode must be --dry-run or --apply"; exit 1 ;;
esac

dupe-engine prune-calibration-run "$RUN_DIR" --mode analysis-only $APPLY
