#!/usr/bin/env bash
# Start the Review UI server on localhost and expose it via Tailscale Funnel.
#
# Provisions: all local (no SQS, S3, or DynamoDB env vars set).
# TLS is terminated by Tailscale — DUPE_TLS_TERMINATED=true acknowledges this.
#
# Usage:
#   ./scripts/start_review_ui_funnel.sh [--port PORT] [--token YOUR_BEARER_TOKEN]
#
# Example (with a specific token):
#   ./scripts/start_review_ui_funnel.sh --token "my-pilot-token-123"

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

# Ensure tailscale is available
if ! command -v tailscale &>/dev/null; then
  echo "ERROR: tailscale not found. Install from https://tailscale.com/download" >&2
  exit 1
fi

# Set up mock-mode environment (no AWS services needed)
export DUPE_TLS_TERMINATED=true
export DUPE_OPENAI_BASE_URL="${DUPE_OPENAI_BASE_URL:-}"

if [[ -n "$TOKEN" ]]; then
  export DUPE_UI_AUTH_TOKEN="$TOKEN"
  echo "Auth token set."
else
  echo "WARNING: No token set. Server will require one since it is non-loopback."
  echo "  Re-run with --token <value> or set DUPE_UI_AUTH_TOKEN in the environment."
fi

# Job errors are redacted by default (may contain PHI). To see full errors in
# the UI during a pilot, set DUPE_LOG_PHI=true — only do this if the server
# is inaccessible to unauthorized users and you have audit controls in place.
export DUPE_LOG_PHI="${DUPE_LOG_PHI:-false}"
if [[ "$DUPE_LOG_PHI" == "true" ]]; then
  echo "NOTE: DUPE_LOG_PHI=true — job errors will be visible in the UI."
fi

# Start the server on loopback; Tailscale Funnel proxies from the public internet.
# The server sees connections from 127.0.0.1 (via tailscaled local proxy).
echo ""
echo "Starting Review UI on port $PORT..."
echo ""

# Activate Tailscale Funnel in the background
echo "Activating Tailscale Funnel on port $PORT..."
tailscale funnel "$PORT" &
FUNNEL_PID=$!

cleanup() {
  echo ""
  echo "Shutting down Tailscale Funnel..."
  tailscale funnel --remove "$PORT" 2>/dev/null || true
  kill "$FUNNEL_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

sleep 1  # Give tailscaled a moment to register the funnel

# Print the public URL
FUNNEL_URL=$(tailscale funnel status 2>/dev/null | grep -oE 'https://[^ ]+' | head -1 || echo "check: tailscale funnel status")
echo "Public URL: ${FUNNEL_URL:-unknown — run 'tailscale funnel status'}"
echo ""
echo "Local URL:  http://127.0.0.1:$PORT"
echo ""
echo "Manual smoke-test:"
echo "  curl ${FUNNEL_URL:-http://127.0.0.1:$PORT}/api/health"
echo ""

# Start the server (blocks until Ctrl-C)
python -m dupe_engine.cli review-ui --host 127.0.0.1 --port "$PORT"
