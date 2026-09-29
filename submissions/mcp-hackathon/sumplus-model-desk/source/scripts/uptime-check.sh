#!/usr/bin/env bash
# Is the reviewed service still up, still the reviewed build, and still able to
# answer? Run by a scheduled workflow during the review window, and runnable by
# hand:
#
#   BASE=https://sumplus-model-desk-production.up.railway.app ./scripts/uptime-check.sh
#   EXPECTED_COMMIT=<40 hex> ./scripts/uptime-check.sh
#
# Liveness alone is not the question. A service can answer 200 while serving a
# different build, or serve the right build and have stopped being able to
# price anything, so each of those is asserted separately.
set -euo pipefail

BASE="${BASE:-https://sumplus-model-desk-production.up.railway.app}"
fail() { echo "FAIL: $*" >&2; exit 1; }

# One reader for every JSON field, so a body that is not JSON at all fails with
# a sentence rather than a stack trace.
field() {
  python3 -c '
import json, sys
path = sys.argv[1].split(".")
try:
    value = json.load(sys.stdin)
except Exception:
    print("__NOT_JSON__")
    sys.exit(0)
for key in path:
    if not isinstance(value, dict) or key not in value:
        print("__MISSING__")
        sys.exit(0)
    value = value[key]
print(value)
' "$1"
}

echo "checking ${BASE}"

health=$(curl -sS --max-time 30 --fail-with-body "${BASE}/health") || fail "/health did not answer"
status=$(printf '%s' "$health" | field status)
commit=$(printf '%s' "$health" | field commit)
offers=$(printf '%s' "$health" | field catalogue.offers)

[ "$status" != "__NOT_JSON__" ] || fail "/health did not return JSON"
[ "$status" = "ok" ] || fail "/health reports status '${status}'"
printf '%s' "$commit" | grep -Eq '^[0-9a-f]{40}$' || fail "/health carries no 40-character commit: '${commit}'"
[ "$offers" -gt 0 ] 2>/dev/null || fail "/health reports '${offers}' offers, so it has nothing to price against"
echo "  health ok, commit ${commit}, ${offers} offers"

proof=$(curl -sS --max-time 30 --fail-with-body "${BASE}/.well-known/xagent-verification.json") || fail "the verification document did not answer"
proof_commit=$(printf '%s' "$proof" | field commit)
proof_slug=$(printf '%s' "$proof" | field slug)

# The pair has to agree. A deployment answering 200 while serving another build
# is exactly what a plain liveness check reads as healthy.
[ "$proof_commit" = "$commit" ] || fail "the verification document says '${proof_commit}', /health says '${commit}'"
[ "$proof_slug" = "sumplus-model-desk" ] || fail "the verification document names slug '${proof_slug}'"
echo "  verification document agrees, slug ${proof_slug}"

if [ -n "${EXPECTED_COMMIT:-}" ]; then
  [ "$commit" = "$EXPECTED_COMMIT" ] || fail "serving ${commit}, expected ${EXPECTED_COMMIT}"
  echo "  commit matches the expected build"
fi

# Can it still do the work? A build that is up and current but answers nothing
# useful has failed in the way that matters to whoever is reviewing it.
plan=$(curl -sS --max-time 45 --fail-with-body -X POST "${BASE}/v1/plan_call" \
  -H 'content-type: application/json' \
  -d '{"inputTokens":100000,"outputTokens":10000,"baselineModelId":"gpt-5.5","limit":3}') || fail "plan_call did not answer"

plan_error=$(printf '%s' "$plan" | field error)
[ "$plan_error" != "__NOT_JSON__" ] || fail "plan_call did not return JSON"
[ "$plan_error" = "__MISSING__" ] || fail "plan_call returned ${plan_error}"
eligible=$(printf '%s' "$plan" | field eligibleCount)
[ "$eligible" -ge 1 ] 2>/dev/null || fail "plan_call found nothing that could take a routine job"
cheapest=$(printf '%s' "$plan" | python3 -c '
import json, sys
rows = json.load(sys.stdin).get("eligible", [])
if not rows:
    sys.exit("plan_call returned no priced rows")
row = rows[0]
missing = [f for f in ("modelId", "line", "totalCost") if f not in row]
if missing:
    sys.exit("a priced row is missing " + ", ".join(missing))
print(row["modelId"], row["totalCost"]["display"])
') || fail "plan_call did not return a usable row"
echo "  plan_call ok, ${eligible} offers, cheapest ${cheapest}"

rpc=$(curl -sS --max-time 30 --fail-with-body -X POST "${BASE}/mcp" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}') || fail "/mcp did not answer"
tool_count=$(printf '%s' "$rpc" | python3 -c '
import json, sys
try:
    body = json.load(sys.stdin)
except Exception:
    print(-1)
    sys.exit(0)
print(len(body.get("result", {}).get("tools", [])))
')
[ "$tool_count" -ge 5 ] 2>/dev/null || fail "tools/list returned ${tool_count} tools"
echo "  mcp ok, ${tool_count} tools listed"

echo "OK ${BASE} is up, serving ${commit}, and answering."
