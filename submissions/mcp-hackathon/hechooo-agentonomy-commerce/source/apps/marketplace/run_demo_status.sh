#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="$ROOT_DIR/.demo_runtime"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

if [ -f "$ROOT_DIR/.env" ]; then
  set -a
  . "$ROOT_DIR/.env"
  set +a
fi

service_url() {
  case "$1" in
    marketplace_registry_service)
      printf "http://%s:%s" "${MARKETPLACE_REGISTRY_HOST:-127.0.0.1}" "${MARKETPLACE_REGISTRY_PORT:-8050}"
      ;;
    marketplace_mcp_server)
      printf "http://%s:%s/mcp/" "${MARKETPLACE_MCP_HOST:-127.0.0.1}" "${MARKETPLACE_MCP_PORT:-9050}"
      ;;
  esac
}

echo "Clink Marketplace runtime status"
echo
if [ -f "$RUNNER_PID_FILE" ]; then
  runner_pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
  if [ -n "$runner_pid" ] && kill -0 "$runner_pid" >/dev/null 2>&1; then
    echo "Runner: running ($runner_pid)"
  else
    echo "Runner: stale metadata"
  fi
else
  echo "Runner: not running"
fi

echo
printf "%-32s %-10s %-8s %-42s %s\n" "Service" "Status" "PID" "URL" "Log"
printf "%-32s %-10s %-8s %-42s %s\n" "-------" "------" "---" "---" "---"
if [ -f "$PID_FILE" ]; then
  while IFS=$'\t' read -r name pid log_file; do
    status="stopped"
    if [ -n "${pid:-}" ] && kill -0 "$pid" >/dev/null 2>&1; then
      status="running"
    fi
    printf "%-32s %-10s %-8s %-42s %s\n" "$name" "$status" "$pid" "$(service_url "$name")" "$log_file"
  done < "$PID_FILE"
else
  echo "No PID metadata found. Start with bash run_demo.sh"
fi
