#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNTIME_DIR="${CLINK_MODULE_RUNTIME_DIR:-$ROOT_DIR/.demo_runtime}"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"
SERVICE_PIDS=()

cd "$ROOT_DIR"

if [ "${CLINK_NODE_MANAGED:-0}" != "1" ]; then
  if [ ! -f .env ]; then
    echo "Missing .env. Run: cp .env.example .env"
    exit 1
  fi

  set -a
  . ./.env
  set +a
fi

if [ -n "${PYTHON_BIN:-}" ]; then
  PYTHON="$PYTHON_BIN"
elif [ -x "$ROOT_DIR/.venv/bin/python" ]; then
  PYTHON="$ROOT_DIR/.venv/bin/python"
else
  PYTHON="$(command -v python3)"
fi

cleanup() {
  trap - EXIT INT TERM
  for pid in "${SERVICE_PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  wait >/dev/null 2>&1 || true
  rm -f "$PID_FILE" "$RUNNER_PID_FILE"
}

terminate_runner() {
  cleanup
  exit 0
}

trap cleanup EXIT
trap terminate_runner INT TERM

mkdir -p "$LOG_DIR"
if [ -f "$RUNNER_PID_FILE" ]; then
  existing_runner="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
  if [ -n "$existing_runner" ] && kill -0 "$existing_runner" >/dev/null 2>&1; then
    echo "Clink Marketplace is already running (runner $existing_runner)."
    echo "Run: bash run_demo_stop.sh"
    exit 1
  fi
fi

: > "$PID_FILE"
echo "$$" > "$RUNNER_PID_FILE"

"$PYTHON" -m alembic upgrade head

start_service() {
  local name="$1"
  local module="$2"
  local log_file="$LOG_DIR/${name}.log"
  echo "Starting ${name}..."
  "$PYTHON" -m "$module" >"$log_file" 2>&1 &
  local pid=$!
  SERVICE_PIDS+=("$pid")
  printf "%s\t%s\t%s\n" "$name" "$pid" "$log_file" >> "$PID_FILE"
}

start_service "marketplace_registry_service" "services.marketplace_app"
start_service "marketplace_worker" "services.marketplace_worker"
start_service "marketplace_mcp_server" "mcp_servers.marketplace_server"

registry_url="http://${MARKETPLACE_REGISTRY_HOST:-127.0.0.1}:${MARKETPLACE_REGISTRY_PORT:-8050}"
mcp_url="http://${MARKETPLACE_MCP_HOST:-127.0.0.1}:${MARKETPLACE_MCP_PORT:-9050}/mcp/"
startup_path="/healthz"
if [ "${CLINK_NODE_MANAGED:-0}" = "1" ]; then
  # Registry synchronization can legitimately be degraded during the first
  # worker cycle. Node readiness reports that state without killing the API.
  startup_path="/livez"
fi
for _ in $(seq 1 20); do
  if curl -fsS "$registry_url$startup_path" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -fsS "$registry_url$startup_path" >/dev/null 2>&1; then
  echo "Registry did not become ready. Check $LOG_DIR/marketplace_registry_service.log"
  exit 1
fi

for _ in $(seq 1 20); do
  if curl -sS -o /dev/null "$mcp_url" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -sS -o /dev/null "$mcp_url" >/dev/null 2>&1; then
  echo "MCP server did not become ready. Check $LOG_DIR/marketplace_mcp_server.log"
  exit 1
fi

echo
echo "Clink Marketplace is ready."
echo "Registry: $registry_url"
echo "MCP:      $mcp_url"
echo "Logs:     $LOG_DIR"
echo
echo "Press Ctrl+C to stop, or run bash run_demo_stop.sh from another shell."

while true; do
  sleep 5
done
