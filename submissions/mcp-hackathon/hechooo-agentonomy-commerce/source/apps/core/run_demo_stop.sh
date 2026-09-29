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

. "$ROOT_DIR/scripts/runtime_process_identity.sh"

SERVICE_PORTS=(
  "${AUTHORIZATION_SERVICE_PORT:-8013}"
  "${AUTHORIZATION_MCP_PORT:-9013}"
  "${POLICY_SERVICE_PORT:-8015}"
  "${POLICY_MCP_PORT:-9015}"
  "${ACTION_SERVICE_PORT:-8016}"
  "${ACTION_MCP_PORT:-9016}"
  "${AUDIT_SERVICE_PORT:-8017}"
  "${AUDIT_MCP_PORT:-9017}"
  "${ACCOUNT_SERVICE_PORT:-8019}"
  "${FUNDING_SERVICE_PORT:-8018}"
  "${FUNDING_MCP_PORT:-9018}"
)

stop_tracked_pid() {
  local pid="$1"
  local label="$2"
  local expected_cwd="$3"
  local expected_command="$4"
  local expected_start_identity="$5"
  clink_stop_tracked_identity \
    "$label" "$pid" "$ROOT_REALPATH" "$expected_cwd" \
    "$expected_command" "$expected_start_identity" || true
}

stop_metadata_pids() {
  if [ -f "$PID_FILE" ]; then
    while IFS=$'	' read -r name pid _ expected_cwd expected_command expected_start_identity; do
      [ -n "${pid:-}" ] || continue
      stop_tracked_pid \
        "$pid" "$name" \
        "${expected_cwd:-}" \
        "${expected_command:-}" \
        "${expected_start_identity:-}"
    done < "$PID_FILE"
  fi

  if [ -f "$RUNNER_PID_FILE" ]; then
    local runner_name=""
    local runner_pid=""
    local runner_cwd=""
    local runner_command=""
    local runner_start_identity=""
    IFS=$'\t' read -r runner_name runner_pid _ runner_cwd runner_command runner_start_identity < "$RUNNER_PID_FILE" || true
    if [ "$runner_name" = "runner" ] && [ -n "${runner_pid:-}" ]; then
      stop_tracked_pid \
        "$runner_pid" "runner" \
        "$runner_cwd" "$runner_command" "$runner_start_identity"
    fi
  fi
}

print_remaining_ports() {
  local port found=0 lines=""
  for port in "${SERVICE_PORTS[@]}"; do
    if command -v ss >/dev/null 2>&1; then
      lines="$(ss -ltnp 2>/dev/null | awk -v port=":$port" '$4 ~ (port "$") {print $0}' || true)"
    elif command -v lsof >/dev/null 2>&1; then
      lines="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
    else
      lines=""
    fi
    if [ -n "$lines" ]; then
      if [ "$found" -eq 0 ]; then
        echo
        echo "Warning: these Clink Core ports are still listening:"
        found=1
      fi
      echo "$lines"
    fi
  done
  [ "$found" -eq 1 ]
}

echo "Stopping Clink Core runtime..."
stop_metadata_pids

rm -f "$PID_FILE" "$RUNNER_PID_FILE"

if print_remaining_ports; then
  echo "Stopped Clink Core runtime. Some ports are still occupied; inspect the warnings above."
else
  echo "Stopped Clink Core runtime. Control-plane ports are clear."
fi
