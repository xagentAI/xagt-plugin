#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
  bash run_demo_stop.sh >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

bash run_demo_stop.sh >/dev/null 2>&1 || true
mkdir -p .demo_runtime
bash run_demo.sh >.demo_runtime/runtime_smoke.log 2>&1 &
runner_pid=$!

for _ in $(seq 1 30); do
  if curl -fsS "http://${MARKETPLACE_REGISTRY_HOST:-127.0.0.1}:${MARKETPLACE_REGISTRY_PORT:-8050}/healthz" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$runner_pid" >/dev/null 2>&1; then
    cat .demo_runtime/runtime_smoke.log
    exit 1
  fi
  sleep 0.5
done

for _ in $(seq 1 30); do
  if curl -sS -o /dev/null "http://${MARKETPLACE_MCP_HOST:-127.0.0.1}:${MARKETPLACE_MCP_PORT:-9050}/mcp/" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

"${PYTHON_BIN:-.venv/bin/python}" scripts/public_mcp_surface_smoke.py
bash run_demo_status.sh
bash run_demo_stop.sh

if pgrep -f "services.marketplace_app|services.marketplace_worker|mcp_servers.marketplace_server" >/dev/null 2>&1; then
  echo "Marketplace processes remain after stop"
  exit 1
fi

trap - EXIT INT TERM
echo '{"status":"ok","runtime_stopped_cleanly":true}'
