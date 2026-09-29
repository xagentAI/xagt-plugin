#!/usr/bin/env bash

clink_process_is_running() {
  local pid="$1"
  case "$pid" in
    ""|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" >/dev/null 2>&1
}

clink_process_cwd() {
  local pid="$1"
  local cwd=""
  if [ -e "/proc/$pid/cwd" ]; then
    cwd="$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)"
  elif command -v lsof >/dev/null 2>&1; then
    cwd="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
  fi
  [ -n "$cwd" ] || return 1
  (
    cd "$cwd" 2>/dev/null
    pwd -P
  )
}

clink_process_command() {
  local pid="$1"
  local command_text=""
  command_text="$(ps -ww -p "$pid" -o command= 2>/dev/null \
    | sed 's/^[[:space:]]*//;s/[[:space:]]*$//' || true)"
  [ -n "$command_text" ] || return 1
  printf '%s' "$command_text"
}

clink_process_start_identity() {
  local pid="$1"
  local stat=""
  local fields=""
  local started=""
  if [ -r "/proc/$pid/stat" ]; then
    stat="$(cat "/proc/$pid/stat" 2>/dev/null || true)"
    fields="${stat##*) }"
    set -- $fields
    if [ "$#" -ge 20 ]; then
      printf 'linux:%s' "${20}"
      return 0
    fi
    return 1
  fi
  started="$(ps -p "$pid" -o lstart= 2>/dev/null \
    | sed 's/^[[:space:]]*//' || true)"
  [ -n "$started" ] || return 1
  printf 'ps:%s' "$started"
}

clink_capture_process_identity() {
  local pid="$1"
  local cwd=""
  local command_text=""
  local start_identity=""
  clink_process_is_running "$pid" || return 1
  cwd="$(clink_process_cwd "$pid" || true)"
  command_text="$(clink_process_command "$pid" || true)"
  start_identity="$(clink_process_start_identity "$pid" || true)"
  [ -n "$cwd" ] && [ -n "$command_text" ] && [ -n "$start_identity" ] \
    || return 1
  case "$cwd$command_text$start_identity" in
    *$'\t'*|*$'\n'*) return 1 ;;
  esac
  printf '%s\t%s\t%s' "$cwd" "$command_text" "$start_identity"
}

clink_process_matches_identity() {
  local pid="$1"
  local runtime_root="$2"
  local expected_cwd="$3"
  local expected_command="$4"
  local expected_start_identity="$5"
  local actual_cwd=""
  local actual_command=""
  local actual_start_identity=""

  [ -n "$runtime_root" ] \
    && [ -n "$expected_cwd" ] \
    && [ -n "$expected_command" ] \
    && [ -n "$expected_start_identity" ] \
    || return 1
  [ "$expected_cwd" = "$runtime_root" ] || return 1
  clink_process_is_running "$pid" || return 1
  actual_cwd="$(clink_process_cwd "$pid" || true)"
  [ "$actual_cwd" = "$expected_cwd" ] || return 1
  actual_command="$(clink_process_command "$pid" || true)"
  [ "$actual_command" = "$expected_command" ] || return 1
  actual_start_identity="$(clink_process_start_identity "$pid" || true)"
  [ "$actual_start_identity" = "$expected_start_identity" ]
}

clink_wait_for_identity_exit() {
  local pid="$1"
  local runtime_root="$2"
  local expected_cwd="$3"
  local expected_command="$4"
  local expected_start_identity="$5"
  local attempts="${6:-${CLINK_STOP_WAIT_ATTEMPTS:-20}}"
  local interval="${7:-${CLINK_STOP_WAIT_INTERVAL_SECONDS:-0.2}}"
  local attempt=0

  while [ "$attempt" -lt "$attempts" ]; do
    clink_process_is_running "$pid" || return 0
    clink_process_matches_identity \
      "$pid" "$runtime_root" "$expected_cwd" \
      "$expected_command" "$expected_start_identity" || return 2
    sleep "$interval"
    attempt=$((attempt + 1))
  done
  clink_process_is_running "$pid" || return 0
  clink_process_matches_identity \
    "$pid" "$runtime_root" "$expected_cwd" \
    "$expected_command" "$expected_start_identity" || return 2
  return 1
}

clink_stop_tracked_identity() {
  local label="$1"
  local pid="$2"
  local runtime_root="$3"
  local expected_cwd="$4"
  local expected_command="$5"
  local expected_start_identity="$6"
  local wait_status=0

  if ! clink_process_is_running "$pid"; then
    return 0
  fi
  if ! clink_process_matches_identity \
    "$pid" "$runtime_root" "$expected_cwd" \
    "$expected_command" "$expected_start_identity"; then
    echo "Skipping ${label} (${pid}): stale or incomplete process metadata." >&2
    return 2
  fi

  echo "Stopping ${label} (${pid})..."
  if clink_process_matches_identity \
    "$pid" "$runtime_root" "$expected_cwd" \
    "$expected_command" "$expected_start_identity"; then
    kill -TERM "$pid" >/dev/null 2>&1 || true
  else
    echo "Skipping ${label} (${pid}): identity changed before TERM." >&2
    return 2
  fi

  clink_wait_for_identity_exit \
    "$pid" "$runtime_root" "$expected_cwd" \
    "$expected_command" "$expected_start_identity" || wait_status=$?
  [ "$wait_status" -eq 0 ] && return 0
  [ "$wait_status" -eq 2 ] && return 2

  echo "Force stopping ${label} (${pid})..."
  if clink_process_matches_identity \
    "$pid" "$runtime_root" "$expected_cwd" \
    "$expected_command" "$expected_start_identity"; then
    kill -KILL "$pid" >/dev/null 2>&1 || true
  else
    echo "Skipping ${label} (${pid}): identity changed before KILL." >&2
    return 2
  fi
  clink_wait_for_identity_exit \
    "$pid" "$runtime_root" "$expected_cwd" \
    "$expected_command" "$expected_start_identity" 10 \
    "${CLINK_STOP_WAIT_INTERVAL_SECONDS:-0.2}" >/dev/null 2>&1 || true
}
