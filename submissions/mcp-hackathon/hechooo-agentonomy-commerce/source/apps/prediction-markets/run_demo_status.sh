#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

RUNTIME_DIR="$ROOT_DIR/.demo_runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

service_url() {
  case "$1" in
    prediction_markets_router_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_ROUTER_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_ROUTER_PORT:-8040}" ;;
    prediction_markets_preview_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_PREVIEW_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_PREVIEW_PORT:-8041}" ;;
    prediction_markets_context_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_CONTEXT_HOST:-${PREDICTION_MARKETS_DECISION_HOST:-127.0.0.1}}" "${PREDICTION_MARKETS_CONTEXT_PORT:-${PREDICTION_MARKETS_DECISION_PORT:-8043}}" ;;
    prediction_markets_decision_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_CONTEXT_HOST:-${PREDICTION_MARKETS_DECISION_HOST:-127.0.0.1}}" "${PREDICTION_MARKETS_CONTEXT_PORT:-${PREDICTION_MARKETS_DECISION_PORT:-8043}}" ;;
    prediction_markets_execution_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_EXECUTION_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_EXECUTION_PORT:-8042}" ;;
    prediction_markets_funding_adapter_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_FUNDING_ADAPTER_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_FUNDING_ADAPTER_PORT:-8046}" ;;
    prediction_markets_deposit_wallet_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_DEPOSIT_WALLET_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_DEPOSIT_WALLET_PORT:-8048}" ;;
    prediction_markets_account_binding_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_ACCOUNT_BINDING_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_ACCOUNT_BINDING_PORT:-8047}" ;;
    prediction_markets_sync_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_SYNC_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_SYNC_PORT:-8045}" ;;
    prediction_markets_portfolio_service) printf 'http://%s:%s' "${PREDICTION_MARKETS_PORTFOLIO_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_PORTFOLIO_PORT:-8044}" ;;
    prediction_markets_dashboard_frontend) printf 'http://%s:%s' "${PREDICTION_MARKETS_DASHBOARD_HOST:-0.0.0.0}" "${PREDICTION_MARKETS_DASHBOARD_PORT:-4174}" ;;
    prediction_markets_mcp_server) printf 'http://%s:%s/mcp/' "${PREDICTION_MARKETS_MCP_HOST:-127.0.0.1}" "${PREDICTION_MARKETS_MCP_PORT:-9040}" ;;
    *) printf '-' ;;
  esac
}

print_line() {
  printf '%-36s %-12s %-8s %-50s %s\n' "$1" "$2" "$3" "$4" "$5"
}

echo "Clink Prediction Markets runtime status"
echo
if [ -f "$RUNNER_PID_FILE" ]; then
  runner_pid="$(cat "$RUNNER_PID_FILE" 2>/dev/null || true)"
  if [ -n "$runner_pid" ] && kill -0 "$runner_pid" >/dev/null 2>&1; then
    echo "Runner: running (${runner_pid})"
  else
    echo "Runner: stale metadata (${runner_pid:-unknown})"
  fi
else
  echo "Runner: not running"
fi

echo
print_line "Service" "Status" "PID" "URL" "Log"
print_line "-------" "------" "---" "---" "---"

if [ -f "$PID_FILE" ]; then
  while IFS=$'\t' read -r name pid log_file; do
    status="stopped"
    if [ -n "${pid:-}" ] && kill -0 "$pid" >/dev/null 2>&1; then
      status="running"
    fi
    print_line "$name" "$status" "${pid:-"-"}" "$(service_url "$name")" "${log_file:-"-"}"
  done < "$PID_FILE"
else
  echo "No PID metadata found. Start with bash run_demo.sh"
fi

if [ -d "$LOG_DIR" ]; then
  echo
  echo "Log files:"
  find "$LOG_DIR" -maxdepth 1 -type f | sort
fi
