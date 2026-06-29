#!/usr/bin/env bash
# Deploy the review UI to oreochiserver.
#
# Pulls latest main, rebuilds the Docker image, and hot-swaps the container.
# Data volumes (/data/review_ui_jobs, /data/runs) are preserved across deploys.
#
# Usage:
#   ./scripts/deploy.sh
#   ./scripts/deploy.sh --host myserver   # override SSH host (default: oreochiserver)
#   ./scripts/deploy.sh --dry-run         # print commands without running them

set -euo pipefail

SSH_HOST=oreochiserver
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host)    SSH_HOST="$2"; shift 2 ;;
    --dry-run) DRY_RUN=true; shift ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

run() {
  if $DRY_RUN; then
    echo "[dry-run] $*"
  else
    "$@"
  fi
}

echo "→ Deploying to $SSH_HOST"
echo ""

echo "  [1/4] Pulling latest main..."
run ssh "$SSH_HOST" "cd ~/dupe-engine && git pull"

echo "  [2/4] Running tests..."
run ssh "$SSH_HOST" "cd ~/dupe-engine && python3 -m pytest tests/ -q --tb=short --ignore=tests/test_e2e_server.py"

echo "  [3/4] Building Docker image..."
run ssh "$SSH_HOST" "cd ~/dupe-engine && docker build -f Dockerfile.worker -t dupe-engine-worker:v0.10.9 . 2>&1 | tail -5"

echo "  [4/4] Hot-swapping container..."
run ssh "$SSH_HOST" "
  docker stop review-ui 2>/dev/null || true
  docker rm review-ui 2>/dev/null || true
  docker run -d \
    --name review-ui \
    --restart unless-stopped \
    -p 127.0.0.1:8765:8765 \
    -v /data/runs:/data/runs \
    -v /data/review_ui_jobs:/data/review_ui_jobs \
    dupe-engine-worker:v0.10.9 \
    dupe-engine review-ui \
      --workspace /data/review_ui_jobs \
      --host 0.0.0.0 \
      --port 8765 \
      --no-browser
  sleep 2
  docker logs review-ui --tail 5
"

echo ""
echo "✓ Live at https://oreochiserver.tail0a3a58.ts.net"
