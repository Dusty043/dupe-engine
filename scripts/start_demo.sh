#!/usr/bin/env bash
# Start the Review UI in demo mode — compliance guards are warnings, not hard stops.
#
# Use only on synthetic or test data. Do NOT run against real PHI records.
#
# Usage:
#   ./scripts/start_demo.sh                     # smoke test (bundled example run)
#   ./scripts/start_demo.sh --live              # live upload mode (needs DUPE_OPENAI_API_KEY)
#   ./scripts/start_demo.sh --port 9000         # custom port
#   ./scripts/start_demo.sh --host 0.0.0.0      # expose on LAN (still demo mode)

set -euo pipefail

PORT=8765
HOST=127.0.0.1
LIVE=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)  PORT="$2"; shift 2 ;;
    --host)  HOST="$2"; shift 2 ;;
    --live)  LIVE=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

export DUPE_DEMO_MODE=true
export DUPE_LOG_PHI=false
export DUPE_INCLUDE_TEXT_PREVIEW=false

echo ""
echo "  ╔═══════════════════════════════════════════════╗"
echo "  ║  DEMO MODE — compliance guards are warnings   ║"
echo "  ║  Do not use with real PHI records.            ║"
echo "  ╚═══════════════════════════════════════════════╝"
echo ""

if [[ "$LIVE" == "true" ]]; then
  if [[ -z "${DUPE_OPENAI_API_KEY:-}" && -z "${OPENAI_API_KEY:-}" ]]; then
    echo "ERROR: --live requires DUPE_OPENAI_API_KEY to be set." >&2
    exit 1
  fi
  echo "  Mode:  live upload (OCR enabled)"
  echo "  URL:   http://${HOST}:${PORT}"
  echo ""
  PYTHONPATH=src python -m dupe_engine.cli review-ui \
    --host "$HOST" \
    --port "$PORT" \
    --workspace ./output/demo_jobs
else
  echo "  Mode:  smoke test (bundled example run, no OCR)"
  echo "  URL:   http://${HOST}:${PORT}"
  echo ""
  PYTHONPATH=src python -m dupe_engine.cli review-ui \
    --host "$HOST" \
    --port "$PORT" \
    --run-dir examples/ui_run_example
fi
