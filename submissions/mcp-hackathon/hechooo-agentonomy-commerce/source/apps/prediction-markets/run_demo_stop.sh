#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
ROOT_REALPATH="$(cd "$ROOT_DIR" && pwd -P)"

RUNTIME_DIR="${CLINK_MODULE_RUNTIME_DIR:-$ROOT_DIR/.demo_runtime}"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

SERVICE_PATTERNS=(
  "services/router_service/app.py"
  "services/preview_service/app.py"
  "services/decision_service/app.py"
  "services/execution_service/app.py"
  "services/funding_adapter_service/app.py"
  "services/deposit_wallet_service/app.py"
  "services/account_binding_service/app.py"
  "services/sync_service/app.py"
  "services/portfolio_service/app.py"
  "mcp_servers/prediction_markets_server.py"
  "dashboard_frontend"
  "vite.*4174"
  "npm run dev -- --host"
  "bash run_demo.sh"
)

SERVICE_PORTS=(
  "${PREDICTION_MARKETS_ROUTER_PORT:-8040}"
  "${PREDICTION_MARKETS_PREVIEW_PORT:-8041}"
  "${PREDICTION_MARKETS_CONTEXT_PORT:-${PREDICTION_MARKETS_DECISION_PORT:-8043}}"
  "${PREDICTION_MARKETS_EXECUTION_PORT:-8042}"
  "${PREDICTION_MARKETS_FUNDING_ADAPTER_PORT:-8046}"
  "${PREDICTION_MARKETS_DEPOSIT_WALLET_PORT:-8048}"
  "${PREDICTION_MARKETS_ACCOUNT_BINDING_PORT:-8047}"
  "${PREDICTION_MARKETS_SYNC_PORT:-8045}"
  "${PREDICTION_MARKETS_PORTFOLIO_PORT:-8044}"
  "${PREDICTION_MARKETS_DASHBOARD_PORT:-4174}"
  "${PREDICTION_MARKETS_MCP_PORT:-9040}"
)

log() {
  if [ "${PREDICTION_MARKETS_STOP_QUIET:-false}" != "true" ]; then
    echo "$@"
  fi
}

is_running() {
  local pid="$1"
  [ -n "${pid:-}" ] && kill -0 "$pid" >/dev/null 2>&1
}

process_cwd() {
  local pid="$1"
  if [ -e "/proc/$pid/cwd" ]; then
    readlink -f "/proc/$pid/cwd" 2>/dev/null || true
    return
  fi
  lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' | head -1 || true
}

process_command() {
  ps -p "$1" -o command= 2>/dev/null || true
}

process_in_repo() {
  local pid="$1" cwd="" command_line=""
  cwd="$(process_cwd "$pid")"
  if [ -n "$cwd" ] && { [ "$cwd" = "$ROOT_REALPATH" ] || [[ "$cwd" == "$ROOT_REALPATH/"* ]]; }; then
    return 0
  fi
  command_line="$(process_command "$pid")"
  [[ "$command_line" == *"$ROOT_REALPATH"* ]] || [[ "$command_line" == *"clink-prediction-markets"* ]]
}

wait_for_exit() {
  local pid="$1" attempts="${2:-25}" i=0
  while is_running "$pid" && [ "$i" -lt "$attempts" ]; do
    sleep 0.2
    i=$((i + 1))
  done
  ! is_running "$pid"
}

stop_pid() {
  local pid="$1" label="${2:-process}"
  if ! is_running "$pid"; then
    return 0
  fi
  log "Stopping ${label} (${pid})..."
  kill "$pid" >/dev/null 2>&1 || true
  if ! wait_for_exit "$pid" 25; then
    log "Force stopping ${label} (${pid})..."
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi
}

stop_pid_tree() {
  local pid="$1" label="${2:-process}" child=""
  if ! is_running "$pid"; then
    return 0
  fi
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    stop_pid_tree "$child" "child of ${label}"
  done
  stop_pid "$pid" "$label"
}

stop_from_pid_file() {
  if [ -f "$PID_FILE" ]; then
    while IFS=$'\t' read -r name pid _; do
      [ -n "${pid:-}" ] && stop_pid_tree "$pid" "$name"
    done < "$PID_FILE"
  fi

  if [ -f "$RUNNER_PID_FILE" ]; then
    local runner_pid=""
    runner_pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
    [ -n "${runner_pid:-}" ] && stop_pid_tree "$runner_pid" "runner"
  fi
}

stop_by_patterns() {
  local pattern="$1" pid=""
  while read -r pid; do
    [ -n "${pid:-}" ] || continue
    [ "$pid" != "$$" ] || continue
    if process_in_repo "$pid"; then
      stop_pid_tree "$pid" "residual ${pattern}"
    fi
  done < <(pgrep -f "$pattern" 2>/dev/null || true)
}

stop_by_ports() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local port="$1" pid=""
  while read -r pid; do
    [ -n "${pid:-}" ] || continue
    [ "$pid" != "$$" ] || continue
    stop_pid_tree "$pid" "residual port ${port}"
  done < <(lsof -ti TCP:"$port" 2>/dev/null || true)
}

verify_ports_clear() {
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local busy=0 port="" holders=""
  for port in "${SERVICE_PORTS[@]}"; do
    holders="$(lsof -ti TCP:"$port" 2>/dev/null || true)"
    if [ -n "$holders" ]; then
      echo "Port ${port} is still occupied by PID(s): ${holders}"
      busy=1
    fi
  done
  return "$busy"
}

log "Stopping Clink Prediction Markets runtime..."
stop_from_pid_file

for pattern in "${SERVICE_PATTERNS[@]}"; do
  stop_by_patterns "$pattern"
done

for port in "${SERVICE_PORTS[@]}"; do
  stop_by_ports "$port"
done

rm -f "$PID_FILE" "$RUNNER_PID_FILE"

if verify_ports_clear; then
  log "Stopped Clink Prediction Markets runtime. Demo ports are clear."
else
  echo "Stopped known Clink Prediction Markets processes, but one or more demo ports are still occupied."
  exit 1
fi
