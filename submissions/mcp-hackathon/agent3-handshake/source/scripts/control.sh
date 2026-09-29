#!/usr/bin/env bash
# Control experiment for verify.mjs.
#
# Each case breaks one specific thing and asserts the verifier goes red, and
# names which assertion must be the one that fails. A break that goes red for
# some other reason proves nothing about the assertion it was aimed at.
#
# Restore is from a copy made before the first edit, never from git: an
# uncommitted working tree would be lost by `git checkout --`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=18899
COMMIT=$(printf 'b%.0s' {1..40})
BACKUP="$(mktemp -d)"
TOUCHED=()

cleanup() {
  for file in "${TOUCHED[@]:-}"; do
    [ -f "$BACKUP/$(basename "$file")" ] && cp -a "$BACKUP/$(basename "$file")" "$ROOT/$file"
  done
  rm -rf "$BACKUP"
  pkill -f "tsx src/server.ts" 2>/dev/null || true
}
trap cleanup EXIT

save() {
  local file="$1"
  if [ ! -f "$BACKUP/$(basename "$file")" ]; then
    cp -a "$ROOT/$file" "$BACKUP/$(basename "$file")"
    TOUCHED+=("$file")
  fi
}

restore_all() {
  for file in "${TOUCHED[@]:-}"; do
    cp -a "$BACKUP/$(basename "$file")" "$ROOT/$file"
  done
}

boot() {
  pkill -f "tsx src/server.ts" 2>/dev/null || true
  sleep 1
  (cd "$ROOT" && PORT=$PORT REVIEW_COMMIT=$COMMIT nohup ./node_modules/.bin/tsx src/server.ts >/tmp/control.log 2>&1 &)
  for _ in $(seq 1 15); do
    sleep 1
    curl -s --max-time 3 "http://127.0.0.1:$PORT/health" -o /dev/null && return 0
  done
  echo "server did not come up"; cat /tmp/control.log; return 1
}

pass_count=0
fail_count=0

# $1 label, $2 substring that must appear among the failures
expect_red() {
  local label="$1" must="$2"
  boot
  local out
  out=$(cd "$ROOT" && node verify.mjs "http://127.0.0.1:$PORT" "$COMMIT" 2>&1 || true)
  local failed
  failed=$(printf '%s' "$out" | grep -c "^  FAIL" || true)
  if [ "$failed" -eq 0 ]; then
    echo "  ✗ ${label}: verifier stayed green"
    fail_count=$((fail_count + 1))
  elif printf '%s' "$out" | grep -q "FAIL.*${must}"; then
    echo "  ✓ ${label}: red on the intended assertion (${failed} failures)"
    pass_count=$((pass_count + 1))
  else
    echo "  ✗ ${label}: red, but not on the intended assertion. Failures were:"
    printf '%s\n' "$out" | grep "^  FAIL" | head -4 | sed 's/^/      /'
    fail_count=$((fail_count + 1))
  fi
  restore_all
}

echo "baseline (must be green)"
boot
if (cd "$ROOT" && node verify.mjs "http://127.0.0.1:$PORT" "$COMMIT" >/tmp/base.txt 2>&1); then
  echo "  ✓ baseline green ($(grep -oE '[0-9]+ passed' /tmp/base.txt))"
  pass_count=$((pass_count + 1))
else
  echo "  ✗ baseline is not green — fix that before trusting anything below"
  tail -5 /tmp/base.txt
  exit 1
fi

echo
echo "breaks (each must be red, on the named assertion)"

save src/server.ts
save src/operations.ts
save src/callspec.ts

# 1. Drop the field the event's verifier compares. Easy to lose in an edit,
#    invisible to every other check.
perl -0pi -e 's/        schemaVersion: 1,\n//' "$ROOT/src/server.ts"
expect_red "well-known drops schemaVersion" "schemaVersion"

# 2. Report a commit that is not the one declared.
perl -0pi -e 's/const COMMIT = process\.env\.REVIEW_COMMIT \?\? "0"\.repeat\(40\);/const COMMIT = "c".repeat(40);/' "$ROOT/src/server.ts"
expect_red "health reports a different commit" "expected commit"

# 3. Route a tool-level refusal through the protocol error channel, so a caller
#    can no longer tell a malformed question from a valid one with a no answer.
perl -0pi -e 's/            isError: !outcome\.ok,/            isError: false,/' "$ROOT/src/server.ts"
expect_red "refusal stops reporting through isError" "isError"

# 4. Make the payment miss-count a constant. The summary still looks plausible.
perl -0pi -e 's/      missedByAModeOnlyReader: missedByModeReader\.length,/      missedByAModeOnlyReader: 0,/' "$ROOT/src/operations.ts"
expect_red "payment miss-count becomes a constant" "mode-only reader"

# 5. Stop treating a relative interface url as a blocker, so the entry falls
#    through and a caller is handed an address it cannot resolve. This aims at
#    `inspect`, not at the null-base branch in callspec.ts: that branch is
#    unreachable while inspect is doing its job, so breaking it changes nothing
#    and would prove nothing.
#    Both the relative url and the missing binding have to be downgraded
#    together: in the live registry the one entry with a relative url also has
#    no http binding, so downgrading either alone leaves it refused for the
#    other reason and the break would prove nothing.
save src/normalize.ts
perl -0pi -e 's/        code: "relative_interface_url",\n        severity: "blocker",/        code: "relative_interface_url",\n        severity: "warning",/' "$ROOT/src/normalize.ts"
perl -0pi -e 's/        code: "operation_without_binding",\n        severity: "blocker",/        code: "operation_without_binding",\n        severity: "warning",/' "$ROOT/src/normalize.ts"
# The service would rather throw its invariant than hand back a guessed host,
# so the break surfaces as a 502 instead of a sendable spec. Either way the
# verifier must notice; what it must never do is stay green.
expect_red "downgrading the relative-url blocker trips the no-guessing invariant" "a refusal is a 404"

# 6. Stop flagging a settlement gateway on a lapsed domain, so a priced call
#    that cannot be paid for is presented as ready to send.
perl -0pi -e 's/          code: "gateway_on_retired_host",\n          severity: "blocker",/          code: "gateway_on_retired_host",\n          severity: "warning",/' "$ROOT/src/normalize.ts"
expect_red "a dead settlement gateway stops being a blocker" "lapsed domain"

echo
echo "$pass_count passed, $fail_count failed"
[ "$fail_count" -eq 0 ]
