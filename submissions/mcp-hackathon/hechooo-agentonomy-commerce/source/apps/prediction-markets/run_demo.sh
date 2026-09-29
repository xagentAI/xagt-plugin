#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUNTIME_DIR="${CLINK_MODULE_RUNTIME_DIR:-$ROOT_DIR/.demo_runtime}"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

SERVICE_PIDS=()

cleanup() {
  trap - EXIT INT TERM
  if [ "${#SERVICE_PIDS[@]}" -gt 0 ]; then
    echo
    echo "Stopping clink-prediction-markets services..."
    for pid in "${SERVICE_PIDS[@]}"; do
      if kill -0 "$pid" >/dev/null 2>&1; then
        kill "$pid" >/dev/null 2>&1 || true
      fi
    done
    wait >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE" "$RUNNER_PID_FILE"
}

terminate_runner() {
  cleanup
  exit 0
}

if [ "${CLINK_NODE_MANAGED:-0}" != "1" ] && [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

if [ "${PREDICTION_MARKETS_SKIP_PRESTART_CLEANUP:-false}" != "true" ]; then
  echo "Pre-start cleanup: stopping stale clink-prediction-markets processes..."
  PREDICTION_MARKETS_STOP_QUIET=true bash "$ROOT_DIR/run_demo_stop.sh" || true
fi

trap cleanup EXIT
trap terminate_runner INT TERM

mkdir -p "$LOG_DIR"
: > "$PID_FILE"
echo "$$" > "$RUNNER_PID_FILE"

if [ -z "${PYTHON_BIN:-}" ] && [ -n "${CONDA_PREFIX:-}" ] && [ -x "$CONDA_PREFIX/bin/python3" ]; then
  PYTHON_BIN="$CONDA_PREFIX/bin/python3"
fi
PYTHON_BIN="${PYTHON_BIN:-python3}"
echo "Using Python: $("$PYTHON_BIN" -c 'import sys; print(sys.executable)')"

start_service() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/${name}.log"
  echo "Starting ${name}..."
  "$@" >"$log_file" 2>&1 &
  local pid=$!
  SERVICE_PIDS+=("$pid")
  printf '%s\t%s\t%s\n' "$name" "$pid" "$log_file" >> "$PID_FILE"
  sleep 1
  if ! kill -0 "$pid" >/dev/null 2>&1; then
    echo "Failed to start ${name}. Log:"
    cat "$log_file"
    exit 1
  fi
}

start_service "prediction_markets_router_service" "$PYTHON_BIN" services/router_service/app.py
start_service "prediction_markets_preview_service" "$PYTHON_BIN" services/preview_service/app.py
start_service "prediction_markets_context_service" "$PYTHON_BIN" services/decision_service/app.py
start_service "prediction_markets_execution_service" "$PYTHON_BIN" services/execution_service/app.py
start_service "prediction_markets_funding_adapter_service" "$PYTHON_BIN" services/funding_adapter_service/app.py
start_service "prediction_markets_deposit_wallet_service" "$PYTHON_BIN" services/deposit_wallet_service/app.py
start_service "prediction_markets_account_binding_service" "$PYTHON_BIN" services/account_binding_service/app.py
start_service "prediction_markets_sync_service" "$PYTHON_BIN" services/sync_service/app.py
start_service "prediction_markets_portfolio_service" "$PYTHON_BIN" services/portfolio_service/app.py
start_service "prediction_markets_mcp_server" "$PYTHON_BIN" mcp_servers/prediction_markets_server.py

if [ "${PREDICTION_MARKETS_SKIP_LEGACY_DASHBOARD:-false}" = "true" ]; then
  echo "Clink Node Companion replaces the legacy prediction dashboard."
elif command -v npm >/dev/null 2>&1 && [ -d "dashboard_frontend/node_modules" ]; then
  start_service "prediction_markets_dashboard_frontend" bash -lc "cd dashboard_frontend && npm run dev -- --host ${PREDICTION_MARKETS_DASHBOARD_HOST:-0.0.0.0} --port ${PREDICTION_MARKETS_DASHBOARD_PORT:-4174}"
elif command -v npm >/dev/null 2>&1; then
  echo "dashboard_frontend/node_modules is missing. Skipping dashboard frontend."
  echo "Install it with: cd dashboard_frontend && npm install"
else
  echo "npm is not available. Skipping dashboard frontend."
fi

echo
echo "Clink Prediction Markets runtime is ready."
echo "Router:  http://${PREDICTION_MARKETS_ROUTER_HOST:-127.0.0.1}:${PREDICTION_MARKETS_ROUTER_PORT:-8040}"
echo "Preview: http://${PREDICTION_MARKETS_PREVIEW_HOST:-127.0.0.1}:${PREDICTION_MARKETS_PREVIEW_PORT:-8041}"
echo "Context: http://${PREDICTION_MARKETS_CONTEXT_HOST:-${PREDICTION_MARKETS_DECISION_HOST:-127.0.0.1}}:${PREDICTION_MARKETS_CONTEXT_PORT:-${PREDICTION_MARKETS_DECISION_PORT:-8043}}"
echo "Execution: http://${PREDICTION_MARKETS_EXECUTION_HOST:-127.0.0.1}:${PREDICTION_MARKETS_EXECUTION_PORT:-8042}"
echo "Funding Adapter: http://${PREDICTION_MARKETS_FUNDING_ADAPTER_HOST:-127.0.0.1}:${PREDICTION_MARKETS_FUNDING_ADAPTER_PORT:-8046}"
echo "Deposit Wallet: http://${PREDICTION_MARKETS_DEPOSIT_WALLET_HOST:-127.0.0.1}:${PREDICTION_MARKETS_DEPOSIT_WALLET_PORT:-8048}"
echo "Account Binding: http://${PREDICTION_MARKETS_ACCOUNT_BINDING_HOST:-127.0.0.1}:${PREDICTION_MARKETS_ACCOUNT_BINDING_PORT:-8047}"
echo "Sync:    http://${PREDICTION_MARKETS_SYNC_HOST:-127.0.0.1}:${PREDICTION_MARKETS_SYNC_PORT:-8045}"
echo "Portfolio: http://${PREDICTION_MARKETS_PORTFOLIO_HOST:-127.0.0.1}:${PREDICTION_MARKETS_PORTFOLIO_PORT:-8044}"
echo "MCP:     http://${PREDICTION_MARKETS_MCP_HOST:-127.0.0.1}:${PREDICTION_MARKETS_MCP_PORT:-9040}/mcp/"
echo "Dashboard: http://${PREDICTION_MARKETS_DASHBOARD_HOST:-0.0.0.0}:${PREDICTION_MARKETS_DASHBOARD_PORT:-4174}"
echo "Run: python3 scripts/router_unit_smoke.py"
echo "Run: python3 scripts/router_service_smoke.py"
echo "Run: python3 scripts/order_preview_unit_smoke.py"
echo "Run: python3 scripts/execution_unit_smoke.py"
echo "Run: python3 scripts/polymarket_funding_adapter_unit_smoke.py"
echo "Run: python3 scripts/polymarket_deposit_wallet_service_unit_smoke.py"
echo "Run: python3 scripts/polymarket_account_binding_unit_smoke.py"
echo "Run: python3 scripts/sync_service_smoke.py"
echo "Run: python3 scripts/portfolio_unit_smoke.py"
echo "Run: python3 scripts/context_service_smoke.py"
echo "Use bash run_demo_stop.sh to stop the runtime."

while true; do
  sleep 5
done
