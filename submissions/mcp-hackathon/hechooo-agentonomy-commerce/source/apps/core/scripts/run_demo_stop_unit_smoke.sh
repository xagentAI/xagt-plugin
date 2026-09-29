#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
. "$ROOT_DIR/scripts/runtime_process_identity.sh"

fake_pid=""
cleanup() {
  if [ -n "$fake_pid" ] && kill -0 "$fake_pid" >/dev/null 2>&1; then
    kill "$fake_pid" >/dev/null 2>&1 || true
    wait "$fake_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT INT TERM

mkdir -p services/policy_service .demo_runtime
python3 -c 'import time; time.sleep(120)' services/policy_service/app.py >/tmp/clink_core_stop_fake.log 2>&1 &
fake_pid=$!

identity="$(clink_capture_process_identity "$fake_pid")"
IFS=$'\t' read -r process_cwd process_command process_start_identity \
  <<< "$identity"
printf "policy_service\t%s\t%s\t%s\t%s\t%s\n" \
  "$fake_pid" \
  "/tmp/clink_core_stop_fake.log" \
  "$process_cwd" \
  "$process_command" \
  "$process_start_identity" > .demo_runtime/pids.tsv

test_running() { kill -0 "$fake_pid" >/dev/null 2>&1; }
if ! test_running; then
  echo "fake service did not start" >&2
  exit 1
fi

bash run_demo_stop.sh >/tmp/clink_core_stop_smoke.log 2>&1 || {
  cat /tmp/clink_core_stop_smoke.log
  exit 1
}

if test_running; then
  echo "fake service still running after stop" >&2
  kill "$fake_pid" >/dev/null 2>&1 || true
  cat /tmp/clink_core_stop_smoke.log
  exit 1
fi

cat /tmp/clink_core_stop_smoke.log
