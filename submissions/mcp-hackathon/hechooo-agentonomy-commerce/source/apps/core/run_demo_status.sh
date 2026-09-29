#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
ROOT_REALPATH="$(pwd -P)"

RUNTIME_DIR="$ROOT_DIR/.demo_runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

. "$ROOT_DIR/scripts/runtime_process_identity.sh"

if [ -f ".env" ]; then
  set -a
  . ./.env
  set +a
fi

service_url() {
  case "$1" in
    authorization_service) printf "http://%s:%s" "${AUTHORIZATION_SERVICE_HOST:-127.0.0.1}" "${AUTHORIZATION_SERVICE_PORT:-8013}" ;;
    authorization_mcp_server) printf "http://%s:%s/mcp/" "${AUTHORIZATION_MCP_HOST:-127.0.0.1}" "${AUTHORIZATION_MCP_PORT:-9013}" ;;
    policy_service) printf "http://%s:%s" "${POLICY_SERVICE_HOST:-127.0.0.1}" "${POLICY_SERVICE_PORT:-8015}" ;;
    policy_mcp_server) printf "http://%s:%s/mcp/" "${POLICY_MCP_HOST:-127.0.0.1}" "${POLICY_MCP_PORT:-9015}" ;;
    action_service) printf "http://%s:%s" "${ACTION_SERVICE_HOST:-127.0.0.1}" "${ACTION_SERVICE_PORT:-8016}" ;;
    action_mcp_server) printf "http://%s:%s/mcp/" "${ACTION_MCP_HOST:-127.0.0.1}" "${ACTION_MCP_PORT:-9016}" ;;
    audit_service) printf "http://%s:%s" "${AUDIT_SERVICE_HOST:-127.0.0.1}" "${AUDIT_SERVICE_PORT:-8017}" ;;
    audit_mcp_server) printf "http://%s:%s/mcp/" "${AUDIT_MCP_HOST:-127.0.0.1}" "${AUDIT_MCP_PORT:-9017}" ;;
    account_service) printf "http://%s:%s" "${ACCOUNT_SERVICE_HOST:-127.0.0.1}" "${ACCOUNT_SERVICE_PORT:-8019}" ;;
    funding_service) printf "http://%s:%s" "${FUNDING_SERVICE_HOST:-127.0.0.1}" "${FUNDING_SERVICE_PORT:-8018}" ;;
    funding_mcp_server) printf "http://%s:%s/mcp/" "${FUNDING_MCP_HOST:-127.0.0.1}" "${FUNDING_MCP_PORT:-9018}" ;;
    *) printf "-" ;;
  esac
}

print_line() {
  printf "%-28s %-12s %-8s %-50s %s\n" "$1" "$2" "$3" "$4" "$5"
}

echo "Clink Core runtime status"
echo

if [ -f "$RUNNER_PID_FILE" ]; then
  runner_name=""
  runner_pid=""
  runner_cwd=""
  runner_command=""
  runner_start_identity=""
  IFS=$'\t' read -r runner_name runner_pid _ runner_cwd runner_command \
    runner_start_identity < "$RUNNER_PID_FILE" || true
  if [ "$runner_name" = "runner" ] \
    && clink_process_matches_identity \
      "$runner_pid" "$ROOT_REALPATH" "$runner_cwd" \
      "$runner_command" "$runner_start_identity"; then
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
  while IFS=$'\t' read -r name pid log_file expected_cwd expected_command \
    expected_start_identity; do
    status="stale"
    if clink_process_matches_identity \
      "${pid:-}" "$ROOT_REALPATH" "${expected_cwd:-}" \
      "${expected_command:-}" "${expected_start_identity:-}"; then
      status="running"
    fi
    print_line "$name" "$status" "${pid:-"-"}" "$(service_url "$name")" "${log_file:-"-"}"
  done < "$PID_FILE"
else
  echo "No PID metadata found. Start Clink Core with bash run_demo.sh"
fi

if [ -d "$LOG_DIR" ]; then
  echo
  echo "Log files:"
  find "$LOG_DIR" -maxdepth 1 -type f | sort
fi
