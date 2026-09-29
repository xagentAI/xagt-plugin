#!/usr/bin/env bash
# OKX ASP self-call harness — free-trial POST per service (usage / demo evidence).
# Safe: read-only research endpoints, no OKX listing mutation.
set -euo pipefail

BASE="${OKX_ASP_BASE:-https://api.leolabs.me}"
SLUG="${PM_DEMO_SLUG:-will-egypt-win-the-2026-fifa-world-cup}"
OUT_DIR="${OKX_SELF_CALL_OUT:-/tmp/okx-asp-self-call}"
mkdir -p "$OUT_DIR"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$OUT_DIR/self-call-$STAMP.jsonl"

post() {
  local path="$1"
  local body="$2"
  local outfile="$OUT_DIR/$(echo "$path" | tr '/' '_')-$STAMP.json"
  echo "==> POST $path"
  http_code=$(curl -sS -o "$outfile" -w '%{http_code}' \
    -X POST "$BASE$path" \
    -H 'content-type: application/json' \
    -d "$body")
  echo "{\"path\":\"$path\",\"http_code\":$http_code,\"file\":\"$outfile\"}" >> "$LOG"
  if [[ "$http_code" != "200" ]]; then
    echo "WARN: $path returned $http_code" >&2
  else
    python3 -c "import json; d=json.load(open('$outfile')); print('  ', d.get('service_id'), d.get('mode'), d.get('billing',{}).get('mode','paid'))" 2>/dev/null || true
  fi
}

post '/agent-delivery-acceptance-audit' '{"task":"Self-call smoke","delivery_summary":"npm test passes on worker deploy.","artifacts":["worker/index.mjs"],"validation":["npm test"]}'
post '/token-dd-verdict' '{"asset":"ETH"}'
post '/event-price-divergence-radar' '{"asset":"bitcoin","limit":2}'
post '/pm-event-readout' "{\"slug\":\"$SLUG\"}"
post '/content-verify-claims' '{"claims":["Demo claim with 358 ASPs."],"sources":[{"text":"Scan shows 358 ASPs on marketplace."}]}'
post '/pm-trade-preflight' "{\"slug\":\"$SLUG\",\"side\":\"yes\",\"size_usd\":50}"
post '/crypto-market-regime-radar' '{"focus":"bitcoin","limit":2}'

echo "Done. Log: $LOG"
