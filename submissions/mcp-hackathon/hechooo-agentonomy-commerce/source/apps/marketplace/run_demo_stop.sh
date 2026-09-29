#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${CLINK_MODULE_RUNTIME_DIR:-$ROOT_DIR/.demo_runtime}"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

stop_pid() {
  local label="$1"
  local pid="$2"
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    echo "Stopping ${label} (${pid})..."
    kill "$pid" >/dev/null 2>&1 || true
  fi
}

echo "Stopping Clink Marketplace runtime..."
if [ -f "$PID_FILE" ]; then
  while IFS=$'\t' read -r name pid _; do
    stop_pid "$name" "${pid:-}"
  done < "$PID_FILE"
fi
if [ -f "$RUNNER_PID_FILE" ]; then
  stop_pid "runner" "$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
fi

sleep 1

# Absolute script paths make this cleanup project-scoped even when PID metadata is stale.
for script in \
  "services.marketplace_app" \
  "services.marketplace_worker" \
  "mcp_servers.marketplace_server"; do
  while IFS= read -r pid; do
    [ -n "$pid" ] || continue
    kill "$pid" >/dev/null 2>&1 || true
    sleep 0.2
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done < <(pgrep -f "$script" || true)
done

rm -f "$PID_FILE" "$RUNNER_PID_FILE"
echo "Stopped Clink Marketplace runtime."
