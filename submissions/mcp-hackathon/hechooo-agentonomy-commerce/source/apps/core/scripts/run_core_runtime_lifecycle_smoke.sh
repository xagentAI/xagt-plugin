#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMP_DIR="$(mktemp -d)"
SANDBOX="$TEMP_DIR/runtime"
FAKE_BIN="$TEMP_DIR/bin"
FAKE_RUNTIME_LOG="$TEMP_DIR/runtime-events.log"
RUNNER_PID=""
WATCHDOG_PID=""
RUNNER_REAPER_GUARD_PID=""
RUNNER_REAPER_GUARD_MARKER="$TEMP_DIR/runner-reaper-guard-activated"
STALE_PID=""
CHANGING_PID=""
LIVE_RUNTIME_PID=""

terminate_and_wait_helper() {
  local pid="$1"
  [ -n "$pid" ] || return 0
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
  wait "$pid" >/dev/null 2>&1 || true
}

start_runner_reaper_guard() {
  local runner_pid="$1"
  (
    sleep "${CLINK_LIFECYCLE_REAPER_GUARD_DELAY_SECONDS:-2}"
    : > "$RUNNER_REAPER_GUARD_MARKER"
    kill "$runner_pid" >/dev/null 2>&1 || true
    sleep 0.2
    kill -9 "$runner_pid" >/dev/null 2>&1 || true
  ) &
  RUNNER_REAPER_GUARD_PID=$!
}

assert_runner_reaper_guard_inactive() {
  if [ -e "$RUNNER_REAPER_GUARD_MARKER" ]; then
    echo "runner reaper guard activated" >&2
    return 1
  fi
}

cleanup() {
  trap - EXIT INT TERM
  terminate_and_wait_helper "$RUNNER_REAPER_GUARD_PID"
  RUNNER_REAPER_GUARD_PID=""
  terminate_and_wait_helper "$WATCHDOG_PID"
  WATCHDOG_PID=""

  : > "$TEMP_DIR/cleanup-pids"
  printf '%s\n' "$RUNNER_PID" "$STALE_PID" "$CHANGING_PID" \
    "$LIVE_RUNTIME_PID" \
    >> "$TEMP_DIR/cleanup-pids"
  if [ -f "$SANDBOX/.demo_runtime/pids.tsv" ]; then
    while IFS=$'\t' read -r _ pid _; do
      [ -n "${pid:-}" ] && printf '%s\n' "$pid" >> "$TEMP_DIR/cleanup-pids"
    done < "$SANDBOX/.demo_runtime/pids.tsv"
  fi
  while read -r pid; do
    [ -n "$pid" ] || continue
    kill "$pid" >/dev/null 2>&1 || true
  done < "$TEMP_DIR/cleanup-pids"
  sleep 0.1
  while read -r pid; do
    [ -n "$pid" ] || continue
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill -9 "$pid" >/dev/null 2>&1 || true
    fi
  done < "$TEMP_DIR/cleanup-pids"
  while read -r pid; do
    [ -n "$pid" ] || continue
    wait "$pid" >/dev/null 2>&1 || true
  done < "$TEMP_DIR/cleanup-pids"
  rm -rf "$TEMP_DIR"
}
trap cleanup EXIT
trap 'exit 124' INT TERM

WATCHDOG_PYTHON="$(command -v python3)"
export REAL_PYTHON="$WATCHDOG_PYTHON"
if [ "${CLINK_LIFECYCLE_REAPER_GUARD_SELF_TEST:-0}" = "1" ]; then
  "$WATCHDOG_PYTHON" -c '
import signal
import time

signal.signal(signal.SIGTERM, signal.SIG_IGN)
time.sleep(300)
' &
  RUNNER_PID=$!
  start_runner_reaper_guard "$RUNNER_PID"
  wait "$RUNNER_PID" >/dev/null 2>&1 || true
  RUNNER_PID=""
  terminate_and_wait_helper "$RUNNER_REAPER_GUARD_PID"
  RUNNER_REAPER_GUARD_PID=""
  assert_runner_reaper_guard_inactive
  exit 0
fi

PARENT_PID=$$
"$WATCHDOG_PYTHON" -c '
import os
import signal
import sys
import time

time.sleep(float(sys.argv[1]))
os.kill(int(sys.argv[2]), signal.SIGTERM)
' "${CLINK_LIFECYCLE_SMOKE_TIMEOUT_SECONDS:-30}" "$PARENT_PID" &
WATCHDOG_PID=$!

mkdir -p "$SANDBOX/scripts" "$FAKE_BIN"
cp "$ROOT_DIR/run_demo.sh" "$SANDBOX/run_demo.sh"
cp "$ROOT_DIR/run_demo_stop.sh" "$SANDBOX/run_demo_stop.sh"
cp "$ROOT_DIR/run_demo_status.sh" "$SANDBOX/run_demo_status.sh"
cp "$ROOT_DIR/scripts/runtime_process_identity.sh" \
  "$SANDBOX/scripts/runtime_process_identity.sh"
. "$SANDBOX/scripts/runtime_process_identity.sh"

cat > "$SANDBOX/.env" <<'ENV'
CLINK_ACCOUNT_PUBLIC_BASE_URL=http://127.0.0.1:8019
CLINK_CORE_INTERNAL_API_TOKEN=lifecycle-smoke-local-token
ENV

cat > "$FAKE_BIN/python3" <<'SHIM'
#!/usr/bin/env bash
set -euo pipefail

if [ "${1:-}" = "scripts/check_runtime_config.py" ]; then
  printf 'config\n' >> "$FAKE_RUNTIME_LOG"
  [ "${FAKE_CONFIG_FAIL:-0}" = "0" ]
  exit 0
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "alembic" ]; then
  printf 'migration\n' >> "$FAKE_RUNTIME_LOG"
  [ "${FAKE_MIGRATION_FAIL:-0}" = "0" ]
  exit 0
fi
if [ "${1:-}" = "-m" ] && [ "${2:-}" = "services.account_service.app" ]; then
  printf 'service:services/account_service/app.py\n' >> "$FAKE_RUNTIME_LOG"
  exec "$REAL_PYTHON" -c 'import time; time.sleep(300)' "$2"
fi
if [ "${1:-}" = "scripts/check_runtime_schema.py" ]; then
  printf 'schema\n' >> "$FAKE_RUNTIME_LOG"
  [ "${FAKE_SCHEMA_FAIL:-0}" = "0" ]
  exit 0
fi
if [ "${1:-}" = "scripts/import_legacy_action_policy_jsonl.py" ]; then
  printf 'legacy_import\n' >> "$FAKE_RUNTIME_LOG"
  [ "${FAKE_LEGACY_IMPORT_FAIL:-0}" = "0" ]
  exit 0
fi
case "${1:-}" in
  services/*|mcp_servers/*)
    printf 'service:%s\n' "$1" >> "$FAKE_RUNTIME_LOG"
    exec "$REAL_PYTHON" -c 'import time; time.sleep(300)' "$1"
    ;;
esac

printf 'unexpected python3 invocation: %s\n' "$*" >&2
exit 97
SHIM
chmod +x "$FAKE_BIN/python3"
export FAKE_RUNTIME_LOG

run_failure_case() {
  local failure_name="$1"
  local expected_events="$2"
  shift 2
  rm -rf "$SANDBOX/.demo_runtime"
  : > "$FAKE_RUNTIME_LOG"

  if env PATH="$FAKE_BIN:$PATH" CLINK_RUNTIME_STARTUP_DELAY_SECONDS=0 "$@" \
    bash "$SANDBOX/run_demo.sh" >"$TEMP_DIR/${failure_name}.out" 2>&1; then
    echo "$failure_name unexpectedly started" >&2
    exit 1
  fi
  actual_events="$(cat "$FAKE_RUNTIME_LOG")"
  if [ "$actual_events" != "$expected_events" ]; then
    cat "$TEMP_DIR/${failure_name}.out" >&2
    printf '%s expected events:\n%s\nactual events:\n%s\n' \
      "$failure_name" "$expected_events" "$actual_events" >&2
    exit 1
  fi
}

run_failure_case configuration "config" \
  FAKE_CONFIG_FAIL=1 FAKE_MIGRATION_FAIL=0 FAKE_SCHEMA_FAIL=0
echo "configuration failure prefix: config only"

run_failure_case migration "config
migration" FAKE_CONFIG_FAIL=0 FAKE_MIGRATION_FAIL=1 FAKE_SCHEMA_FAIL=0
echo "migration failure prefix: config, migration"

run_failure_case schema "config
migration
schema" FAKE_CONFIG_FAIL=0 FAKE_MIGRATION_FAIL=0 FAKE_SCHEMA_FAIL=1
echo "schema failure prefix: config, migration, schema"

run_failure_case legacy-import "config
migration
schema
legacy_import" FAKE_CONFIG_FAIL=0 FAKE_MIGRATION_FAIL=0 FAKE_SCHEMA_FAIL=0 \
  FAKE_LEGACY_IMPORT_FAIL=1
echo "legacy import failure prefix: config, migration, schema, legacy import"

rm -rf "$SANDBOX/.demo_runtime"
mkdir -p "$SANDBOX/.demo_runtime"
(
  cd "$SANDBOX"
  exec "$REAL_PYTHON" -c 'import time; time.sleep(300)' run_demo.sh
) &
LIVE_RUNTIME_PID=$!
sleep 0.05
live_runner_identity="$(clink_capture_process_identity "$LIVE_RUNTIME_PID")"
IFS=$'\t' read -r live_runner_cwd live_runner_command \
  live_runner_start_identity <<< "$live_runner_identity"
printf "runner\t%s\t-\t%s\t%s\t%s\n" \
  "$LIVE_RUNTIME_PID" "$live_runner_cwd" "$live_runner_command" \
  "$live_runner_start_identity" > "$SANDBOX/.demo_runtime/runner.pid"
: > "$FAKE_RUNTIME_LOG"
if env PATH="$FAKE_BIN:$PATH" CLINK_RUNTIME_STARTUP_DELAY_SECONDS=0 \
  bash "$SANDBOX/run_demo.sh" >"$TEMP_DIR/already-running.out" 2>&1; then
  echo "already-running runtime unexpectedly started" >&2
  exit 1
fi
if [ -s "$FAKE_RUNTIME_LOG" ]; then
  cat "$FAKE_RUNTIME_LOG" >&2
  echo "already-running runtime reached startup validation or migrations" >&2
  exit 1
fi
if ! kill -0 "$LIVE_RUNTIME_PID" >/dev/null 2>&1; then
  echo "already-running runtime was signaled by duplicate startup" >&2
  exit 1
fi
for env_case in missing malformed side_effect; do
  case "$env_case" in
    missing)
      rm -f "$SANDBOX/.env"
      ;;
    malformed)
      printf 'if )\n' > "$SANDBOX/.env"
      ;;
    side_effect)
      env_side_effect="$TEMP_DIR/env-side-effect"
      rm -f "$env_side_effect"
      printf 'touch %q\n' "$env_side_effect" > "$SANDBOX/.env"
      ;;
  esac
  : > "$FAKE_RUNTIME_LOG"
  if env PATH="$FAKE_BIN:$PATH" CLINK_RUNTIME_STARTUP_DELAY_SECONDS=0 \
    bash "$SANDBOX/run_demo.sh" >"$TEMP_DIR/already-running-${env_case}.out" 2>&1; then
    echo "already-running runtime accepted ${env_case} .env" >&2
    exit 1
  fi
  if [ -s "$FAKE_RUNTIME_LOG" ]; then
    cat "$FAKE_RUNTIME_LOG" >&2
    echo "already-running runtime read ${env_case} .env before checking runtime" >&2
    exit 1
  fi
  if ! grep -q 'already running' "$TEMP_DIR/already-running-${env_case}.out"; then
    cat "$TEMP_DIR/already-running-${env_case}.out" >&2
    echo "already-running runtime did not fail from runtime availability" >&2
    exit 1
  fi
  if [ "$env_case" = "side_effect" ] && [ -e "$env_side_effect" ]; then
    echo "already-running runtime executed .env side effect" >&2
    exit 1
  fi
done
cat > "$SANDBOX/.env" <<'ENV'
CLINK_ACCOUNT_PUBLIC_BASE_URL=http://127.0.0.1:8019
CLINK_CORE_INTERNAL_API_TOKEN=lifecycle-smoke-local-token
ENV
terminate_and_wait_helper "$LIVE_RUNTIME_PID"
LIVE_RUNTIME_PID=""
rm -rf "$SANDBOX/.demo_runtime"
echo "already-running runtime: exited before config, migration, schema, and legacy import"
echo "already-running runtime: skipped unreadable .env files"

rm -rf "$SANDBOX/.demo_runtime"
mkdir -p "$SANDBOX/.demo_runtime"
(
  cd "$SANDBOX"
  exec "$REAL_PYTHON" -c 'import time; time.sleep(300)' services/policy_service/app.py
) &
STALE_PID=$!
sleep 0.05
stale_command="$(clink_process_command "$STALE_PID")"

printf "policy_service\t%s\t%s\n" \
  "$STALE_PID" "$TEMP_DIR/unrelated.log" > "$SANDBOX/.demo_runtime/pids.tsv"
bash "$SANDBOX/run_demo_stop.sh" >"$TEMP_DIR/stale-old-stop.out" 2>&1
if ! kill -0 "$STALE_PID" >/dev/null 2>&1; then
  echo "old PID metadata killed an unrelated process" >&2
  exit 1
fi

mkdir -p "$SANDBOX/.demo_runtime"
printf "policy_service\t%s\t%s\t%s\t%s\t%s\n" \
  "$STALE_PID" "$TEMP_DIR/unrelated.log" "$SANDBOX" \
  "$stale_command" "stale-start-identity" \
  > "$SANDBOX/.demo_runtime/pids.tsv"
printf "runner\t%s\t-\t%s\t%s\t%s\n" \
  "$STALE_PID" "$SANDBOX" "$stale_command" "stale-start-identity" \
  > "$SANDBOX/.demo_runtime/runner.pid"
printf "funding_service\t%s\t%s\n" \
  "$STALE_PID" "$TEMP_DIR/incomplete.log" >> "$SANDBOX/.demo_runtime/pids.tsv"
status_output="$(bash "$SANDBOX/run_demo_status.sh")"
if grep -Eq '^(Runner: running|policy_service[[:space:]]+running)' \
  <<< "$status_output"; then
  printf '%s\n' "$status_output" >&2
  echo "reused PID metadata was reported running" >&2
  exit 1
fi
bash "$SANDBOX/run_demo_stop.sh" >"$TEMP_DIR/stale-complete-stop.out" 2>&1
if ! kill -0 "$STALE_PID" >/dev/null 2>&1; then
  echo "complete stale PID metadata received a stop signal" >&2
  exit 1
fi
mkdir -p "$SANDBOX/.demo_runtime"
printf "policy_service\t%s\t%s\t%s\t%s\t%s\n" \
  "$STALE_PID" "$TEMP_DIR/unrelated.log" "$SANDBOX" \
  "$stale_command" "stale-start-identity" \
  > "$SANDBOX/.demo_runtime/pids.tsv"
printf "funding_service\t%s\t%s\n" \
  "$STALE_PID" "$TEMP_DIR/incomplete.log" >> "$SANDBOX/.demo_runtime/pids.tsv"
printf "runner\t%s\t-\t%s\t%s\t%s\n" \
  "$STALE_PID" "$SANDBOX" "$stale_command" "stale-start-identity" \
  > "$SANDBOX/.demo_runtime/runner.pid"

: > "$FAKE_RUNTIME_LOG"
env PATH="$FAKE_BIN:$PATH" \
  CLINK_RUNTIME_STARTUP_DELAY_SECONDS=0 \
  FAKE_CONFIG_FAIL=0 \
  FAKE_MIGRATION_FAIL=0 \
  FAKE_SCHEMA_FAIL=0 \
  FAKE_LEGACY_IMPORT_FAIL=0 \
  bash "$SANDBOX/run_demo.sh" >"$TEMP_DIR/success.out" 2>&1 &
RUNNER_PID=$!

started=0
attempt=0
while [ "$attempt" -lt 250 ]; do
  if [ -f "$SANDBOX/.demo_runtime/pids.tsv" ] \
    && [ "$(wc -l < "$SANDBOX/.demo_runtime/pids.tsv")" -eq 11 ] \
    && grep -q '^account_service' "$SANDBOX/.demo_runtime/pids.tsv"; then
    started=1
    break
  fi
  if ! kill -0 "$RUNNER_PID" >/dev/null 2>&1; then
    cat "$TEMP_DIR/success.out" >&2
    echo "reused PID metadata blocked a fresh runtime" >&2
    exit 1
  fi
  sleep 0.02
  attempt=$((attempt + 1))
done
if [ "$started" -ne 1 ]; then
  cat "$TEMP_DIR/success.out" >&2
  echo "runtime did not record every service" >&2
  exit 1
fi
if ! kill -0 "$STALE_PID" >/dev/null 2>&1; then
  echo "startup cleanup signaled reused PID metadata" >&2
  exit 1
fi
echo "reused pid metadata: stale in status, did not block or receive signals"

expected_success_prefix="config
migration
schema
legacy_import
service:services/authorization_service/app.py"
actual_success_prefix="$(sed -n '1,5p' "$FAKE_RUNTIME_LOG")"
if [ "$actual_success_prefix" != "$expected_success_prefix" ]; then
  printf 'success prefix mismatch:\n%s\n' "$actual_success_prefix" >&2
  exit 1
fi
if ! grep -qx 'service:services/account_service/app.py' "$FAKE_RUNTIME_LOG"; then
  echo "account service start was not logged" >&2
  exit 1
fi

status_output="$(bash "$SANDBOX/run_demo_status.sh")"
if ! grep -Eq '^account_service[[:space:]]+running' <<< "$status_output"; then
  printf '%s\n' "$status_output" >&2
  echo "account service was not reported running" >&2
  exit 1
fi
echo "account_service: running"

cut -f2 "$SANDBOX/.demo_runtime/pids.tsv" > "$TEMP_DIR/service-pids"
bash "$SANDBOX/run_demo_stop.sh" >"$TEMP_DIR/stop.out" 2>&1
if ! grep -q 'Stopping account_service' "$TEMP_DIR/stop.out"; then
  cat "$TEMP_DIR/stop.out" >&2
  echo "account service stop was not logged" >&2
  exit 1
fi
if grep -q 'Force stopping runner' "$TEMP_DIR/stop.out"; then
  cat "$TEMP_DIR/stop.out" >&2
  echo "legitimate runner required SIGKILL" >&2
  exit 1
fi
start_runner_reaper_guard "$RUNNER_PID"
wait "$RUNNER_PID" >/dev/null 2>&1 || true
RUNNER_PID=""
terminate_and_wait_helper "$RUNNER_REAPER_GUARD_PID"
RUNNER_REAPER_GUARD_PID=""
assert_runner_reaper_guard_inactive

while read -r pid; do
  if [ -n "$pid" ] && kill -0 "$pid" >/dev/null 2>&1; then
    cat "$TEMP_DIR/stop.out" >&2
    echo "service process $pid survived stop" >&2
    exit 1
  fi
done < "$TEMP_DIR/service-pids"
if [ -e "$SANDBOX/.demo_runtime/pids.tsv" ] \
  || [ -e "$SANDBOX/.demo_runtime/runner.pid" ]; then
  echo "runtime metadata survived stop" >&2
  exit 1
fi
echo "successful lifecycle: ordered prefix and account service stopped"

mkdir -p "$SANDBOX/.demo_runtime" "$TEMP_DIR/changed-cwd"
CHANGED_CWD="$(cd "$TEMP_DIR/changed-cwd" && pwd -P)"
(
  cd "$SANDBOX"
  exec "$REAL_PYTHON" -c '
import os
import signal
import sys
import time

signal.signal(signal.SIGTERM, lambda *_: os.chdir(sys.argv[1]))
time.sleep(300)
' "$CHANGED_CWD"
) &
CHANGING_PID=$!
sleep 0.05
identity="$(clink_capture_process_identity "$CHANGING_PID")"
IFS=$'\t' read -r changing_cwd changing_command changing_start_identity \
  <<< "$identity"
printf "policy_service\t%s\t%s\t%s\t%s\t%s\n" \
  "$CHANGING_PID" "$TEMP_DIR/changing.log" "$changing_cwd" \
  "$changing_command" "$changing_start_identity" \
  > "$SANDBOX/.demo_runtime/pids.tsv"
CLINK_STOP_WAIT_ATTEMPTS=10 CLINK_STOP_WAIT_INTERVAL_SECONDS=0.05 \
  bash "$SANDBOX/run_demo_stop.sh" >"$TEMP_DIR/changing-stop.out" 2>&1
attempt=0
while [ "$attempt" -lt 20 ]; do
  [ "$(clink_process_cwd "$CHANGING_PID" || true)" = "$CHANGED_CWD" ] \
    && break
  sleep 0.02
  attempt=$((attempt + 1))
done
if ! kill -0 "$CHANGING_PID" >/dev/null 2>&1; then
  cat "$TEMP_DIR/changing-stop.out" >&2
  echo "identity-changing process received SIGKILL" >&2
  exit 1
fi
if [ "$(clink_process_cwd "$CHANGING_PID" || true)" != "$CHANGED_CWD" ]; then
  cat "$TEMP_DIR/changing-stop.out" >&2
  echo "identity-changing process did not receive SIGTERM" >&2
  exit 1
fi
echo "identity changed after TERM: SIGKILL skipped"
