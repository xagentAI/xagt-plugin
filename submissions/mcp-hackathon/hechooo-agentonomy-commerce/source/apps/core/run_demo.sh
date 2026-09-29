#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
ROOT_REALPATH="$(pwd -P)"

RUNTIME_DIR="${CLINK_MODULE_RUNTIME_DIR:-$ROOT_DIR/.demo_runtime}"
LOG_DIR="$RUNTIME_DIR/logs"
PID_FILE="$RUNTIME_DIR/pids.tsv"
RUNNER_PID_FILE="$RUNTIME_DIR/runner.pid"

. "$ROOT_DIR/scripts/runtime_process_identity.sh"

SERVICE_IDENTITIES=()
OWNS_RUNTIME_METADATA=0
IDLE_SLEEP_PID=""

stop_idle_sleep() {
  if [ -n "$IDLE_SLEEP_PID" ]; then
    kill "$IDLE_SLEEP_PID" >/dev/null 2>&1 || true
    wait "$IDLE_SLEEP_PID" >/dev/null 2>&1 || true
    IDLE_SLEEP_PID=""
  fi
}

cleanup() {
  trap - EXIT INT TERM
  stop_idle_sleep
  if [ "${#SERVICE_IDENTITIES[@]}" -gt 0 ]; then
    echo
    echo "Stopping Clink Core services..."
    for identity in "${SERVICE_IDENTITIES[@]}"; do
      IFS=$'\t' read -r identity_name identity_pid identity_cwd \
        identity_command identity_start <<< "$identity"
      clink_stop_tracked_identity \
        "$identity_name" "$identity_pid" "$ROOT_REALPATH" "$identity_cwd" \
        "$identity_command" "$identity_start" || true
    done
  fi
  if [ "$OWNS_RUNTIME_METADATA" -eq 1 ]; then
    rm -f "$PID_FILE" "$RUNNER_PID_FILE"
  fi
}

trap cleanup EXIT
trap 'cleanup; exit 130' INT
trap 'cleanup; exit 143' TERM

ensure_runtime_is_available() {
  mkdir -p "$LOG_DIR"

  if [ -f "$RUNNER_PID_FILE" ]; then
    local runner_name=""
    local existing_runner=""
    local runner_cwd=""
    local runner_command=""
    local runner_start_identity=""
    IFS=$'\t' read -r runner_name existing_runner _ runner_cwd \
      runner_command runner_start_identity < "$RUNNER_PID_FILE" || true
    if [ "$runner_name" = "runner" ] \
      && clink_process_matches_identity \
        "$existing_runner" "$ROOT_REALPATH" "$runner_cwd" \
        "$runner_command" "$runner_start_identity"; then
      echo "A Clink Core runtime is already running (runner pid: $existing_runner)."
      echo "Use bash run_demo_stop.sh before starting a new one."
      exit 1
    else
      echo "Ignoring stale runner metadata (${existing_runner:-unknown})."
    fi
  fi

  if [ -f "$PID_FILE" ]; then
    local live_service_pid=""
    while IFS=$'\t' read -r name pid _ expected_cwd expected_command \
      expected_start_identity; do
      if clink_process_matches_identity \
        "${pid:-}" "$ROOT_REALPATH" "${expected_cwd:-}" \
        "${expected_command:-}" "${expected_start_identity:-}"; then
        live_service_pid="$pid"
        break
      fi
      [ -n "${pid:-}" ] \
        && echo "Ignoring stale ${name:-service} metadata (${pid})."
    done < "$PID_FILE"
    if [ -n "$live_service_pid" ]; then
      echo "A Clink Core service is already running (pid: $live_service_pid)."
      echo "Use bash run_demo_stop.sh before starting a new one."
      exit 1
    fi
  fi

  : > "$PID_FILE"
  local runner_identity=""
  local runner_cwd=""
  local runner_command=""
  local runner_start_identity=""
  runner_identity="$(clink_capture_process_identity "$$")" || {
    echo "Unable to capture complete runner process identity." >&2
    exit 1
  }
  IFS=$'\t' read -r runner_cwd runner_command runner_start_identity \
    <<< "$runner_identity"
  printf "runner\t%s\t-\t%s\t%s\t%s\n" \
    "$$" "$runner_cwd" "$runner_command" "$runner_start_identity" \
    > "$RUNNER_PID_FILE"
  OWNS_RUNTIME_METADATA=1
}

start_service() {
  local name="$1"
  shift
  local log_file="$LOG_DIR/${name}.log"
  local identity=""
  local previous_identity=""
  local attempt=0
  local process_cwd=""
  local process_command=""
  local process_start_identity=""

  echo "Starting ${name}..."
  "$@" >"$log_file" 2>&1 &
  local pid=$!
  while [ "$attempt" -lt 20 ]; do
    identity="$(clink_capture_process_identity "$pid" || true)"
    if [ -n "$identity" ] && [ "$identity" = "$previous_identity" ]; then
      break
    fi
    previous_identity="$identity"
    sleep 0.02
    attempt=$((attempt + 1))
  done
  [ -n "$identity" ] && [ "$identity" = "$previous_identity" ] || {
    echo "Failed to capture complete identity for ${name}." >&2
    exit 1
  }
  IFS=$'\t' read -r process_cwd process_command process_start_identity \
    <<< "$identity"
  SERVICE_IDENTITIES+=("${name}"$'\t'"${pid}"$'\t'"${process_cwd}"$'\t'"${process_command}"$'\t'"${process_start_identity}")
  printf "%s\t%s\t%s\t%s\t%s\t%s\n" \
    "$name" "$pid" "$log_file" "$process_cwd" "$process_command" \
    "$process_start_identity" >> "$PID_FILE"
  sleep "${CLINK_RUNTIME_STARTUP_DELAY_SECONDS:-1}"

  if ! clink_process_matches_identity \
    "$pid" "$ROOT_REALPATH" "$process_cwd" "$process_command" \
    "$process_start_identity"; then
    echo "Failed to start ${name}. Log:"
    cat "$log_file"
    exit 1
  fi
}

ensure_runtime_is_available

if [ "${CLINK_NODE_MANAGED:-0}" != "1" ]; then
  if [ ! -f ".env" ]; then
    echo "No .env file found. Create .env before starting Clink Core."
    exit 1
  fi

  set -a
  . ./.env
  set +a
fi

echo "Validating Clink Core runtime configuration..."
if ! PYTHONPATH=. python3 scripts/check_runtime_config.py; then
  echo "Clink Core configuration validation failed; no services were started." >&2
  exit 1
fi

echo "Applying Clink Core database migrations..."
if ! python3 -m alembic upgrade head; then
  echo "Clink Core migrations failed; no services were started." >&2
  exit 1
fi
echo "Validating Clink Core database schema..."
if ! PYTHONPATH=. python3 scripts/check_runtime_schema.py; then
  echo "Clink Core schema validation failed; no services were started." >&2
  exit 1
fi
echo "Importing legacy Action and Policy state..."
if ! PYTHONPATH=. python3 scripts/import_legacy_action_policy_jsonl.py; then
  echo "Clink Core legacy state import failed; no services were started." >&2
  exit 1
fi

start_service "authorization_service" python3 services/authorization_service/app.py
start_service "authorization_mcp_server" python3 mcp_servers/authorization_server.py
start_service "policy_service" python3 services/policy_service/app.py
start_service "policy_mcp_server" python3 mcp_servers/policy_server.py
start_service "action_service" python3 services/action_service/app.py
start_service "action_mcp_server" python3 mcp_servers/action_server.py
start_service "audit_service" python3 services/audit_service/app.py
start_service "audit_mcp_server" python3 mcp_servers/audit_server.py
start_service "account_service" python3 -m services.account_service.app
start_service "funding_service" python3 services/funding_service/app.py
start_service "funding_mcp_server" python3 mcp_servers/funding_server.py

echo
echo "Clink Core control plane runtime is ready."
echo
echo "Service logs are written to $LOG_DIR"
echo "PID file: $PID_FILE"
echo "Use bash run_demo_stop.sh to stop the runtime safely."
echo "Press Ctrl+C to stop all Clink Core processes."

while true; do
  sleep 5 &
  IDLE_SLEEP_PID=$!
  wait "$IDLE_SLEEP_PID" || true
  IDLE_SLEEP_PID=""
done
