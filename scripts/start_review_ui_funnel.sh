#!/usr/bin/env bash
# Start the Review UI on localhost and expose it via Tailscale Funnel.
#
# TLS is terminated by Tailscale. DUPE_TLS_TERMINATED=true silences the
# non-loopback warning — it does not enable or disable any compliance behaviour.
#
# Usage:
#   ./scripts/start_review_ui_funnel.sh [--port PORT] [--token YOUR_BEARER_TOKEN]
#
# Example:
#   ./scripts/start_review_ui_funnel.sh --token "pilot-token-123"

set -euo pipefail

PORT=8765
TOKEN=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --port)   PORT="$2"; shift 2 ;;
    --token)  TOKEN="$2"; shift 2 ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

if ! command -v tailscale &>/dev/null; then
  echo "ERROR: tailscale not found. Install from https://tailscale.com/download" >&2
  exit 1
fi

# Tailscale terminates TLS — silence the non-loopback warning
export DUPE_TLS_TERMINATED=true

if [[ -n "$TOKEN" ]]; then
  export DUPE_UI_AUTH_TOKEN="$TOKEN"
  echo "Auth token set."
else
  echo "WARNING: No token set. Any caller can reach the server."
  echo "  Re-run with --token <value> or set DUPE_UI_AUTH_TOKEN."
fi

echo ""
echo "Starting Review UI on port $PORT..."
echo ""

tailscale funnel "$PORT" &
FUNNEL_PID=$!

cleanup() {
  echo ""
  echo "Shutting down Tailscale Funnel..."
  tailscale funnel --remove "$PORT" 2>/dev/null || true
  kill "$FUNNEL_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 1

FUNNEL_URL=$(tailscale funnel status 2>/dev/null | grep -oE 'https://[^ ]+' | head -1 || true)
echo "Public URL: ${FUNNEL_URL:-unknown — run 'tailscale funnel status'}"
echo "Local URL:  http://127.0.0.1:$PORT"
echo ""

python -m dupe_engine.cli review-ui --host 127.0.0.1 --port "$PORT"
