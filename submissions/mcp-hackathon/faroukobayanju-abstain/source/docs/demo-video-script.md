# Demo video script

The official X-Agent submission contract does not require a video, but a short recording makes Abstain's value and proof easier for judges to understand. Target 2 minutes 30 seconds. Record at 1440p or 1080p with terminal text at least 20 pt.

## Before recording

1. Close notifications, private terminals, dashboards, `.env` files, and password managers.
2. Open three prepared tabs only: this README, the live API health URL, and a terminal in the repository.
3. Increase terminal font size and clear scrollback.
4. Put the demo key in the shell environment without showing it on screen:

   ```bash
   export ABSTAIN_DEMO_KEY='your-demo-key'
   export ABSTAIN_URL='https://x-agent-six.vercel.app'
   ```

5. Confirm the live signal and chain before recording:

   ```bash
   curl -s "$ABSTAIN_URL/health" | jq
   curl -s "$ABSTAIN_URL/v1/ready" | jq
   curl -s "$ABSTAIN_URL/v1/verify" | jq
   ```

6. Rehearse once. Keep the final recording below three minutes unless the submission portal later publishes a stricter limit.

## Timed narration and actions

### 0:00–0:12 — Problem

**Say:** “Trading agents can turn a signal into an order instantly, but they usually cannot prove which evidence and rules allowed it, prevent two workers from acting on the same signal, or guarantee their audit log survives a cold start.”

**Show:** The README section “The problem it solves.”

### 0:12–0:25 — Product

**Say:** “Abstain is a pre-trade execution gate built around OlaXBT Nexus. It validates strategy and market evidence, runs ten deterministic checks, and returns EXECUTE, ABSTAIN, or NO_TRADE. Every answer is committed to a public hash chain before the API responds.”

**Show:** The README architecture diagram.

### 0:25–0:40 — Real deployment proof

**Run:**

```bash
curl -s "$ABSTAIN_URL/health" | jq
curl -s "$ABSTAIN_URL/v1/ready" | jq
```

**Say:** “The health response binds this service to the exact public Git commit. Readiness separately proves Nexus is reachable and the receipt store is durable. If production falls back to memory, Abstain returns 503 instead of pretending the evidence is safe.”

### 0:40–1:10 — Golden-path evaluation

**Run:**

```bash
curl -s -X POST "$ABSTAIN_URL/v1/evaluate" \
  -H 'content-type: application/json' \
  -H "x-abstain-key: $ABSTAIN_DEMO_KEY" \
  -d '{"symbol":"BTC/USDT","side":"BUY","notional":15000,"policy":"strict"}' | jq
```

**Say:** “Nexus currently publishes HOLD, so the correct result is NO_TRADE: nothing was proposed, nothing was authorized, and a receipt was still written. When Nexus publishes BUY or SELL, the same endpoint records all ten checks and refuses on missing or unsafe evidence.”

**Pause on:** `verdict`, `policy_hash`, `as_of`, `reason`, `receipt.seq`, and `receipt.hash`.

### 1:10–1:35 — Independent proof

**Run:**

```bash
curl -s "$ABSTAIN_URL/v1/verify" | jq
curl -s "$ABSTAIN_URL/v1/receipts" | jq '.total, .receipts[-1]'
```

**Say:** “Anyone can recompute the chain without credentials. Each receipt links to the previous hash, and verification reports the first divergent sequence if any record is changed or removed.”

### 1:35–1:58 — Failure behavior

**Run:**

```bash
curl -s -X POST "$ABSTAIN_URL/v1/evaluate" \
  -H 'content-type: application/json' \
  -d '{"symbol":"BTC/USDT","side":"BUY","notional":15000}' | jq

curl -s -X POST "$ABSTAIN_URL/v1/evaluate" \
  -H 'content-type: application/json' \
  -H "x-abstain-key: $ABSTAIN_DEMO_KEY" \
  -d '{"symbol":"BTC","side":"BUY","notional":15000}' | jq
```

**Say:** “Writes fail closed without authentication, and invalid input names the exact field. Nexus timeouts, malformed evidence, store failures, and unresolved concurrency also return named safe failures rather than an unrecorded verdict.”

### 1:58–2:18 — Concurrency proof

**Run:**

```bash
./scripts/verify-live.sh "$ABSTAIN_URL" "$ABSTAIN_DEMO_KEY" "$(git rev-parse HEAD)"
```

**Say:** “This canary launches eight concurrent writes against real serverless infrastructure. Redis Lua compare-and-append keeps every sequence unique and the chain gapless, then independently recomputes a receipt hash.”

**Pause on:** the concurrency PASS, chain length, and final passed/failed count.

### 2:18–2:30 — Close

**Say:** “Abstain turns a trading agent’s invisible decision into a fail-closed control and a receipt anyone can verify. Nexus provides the live strategy evidence; Abstain makes every action, refusal, and non-action accountable.”

**Show:** Repository URL and live API URL.

## Recording checklist

- The health commit equals the submitted `reviewCommit`.
- `/v1/ready` shows `ready:true` and `durable:true`.
- No secret value appears in the video, terminal history, title bar, or clipboard manager.
- The terminal output is readable on a phone-sized player.
- Remove dead air and failed takes, but do not splice outputs in a way that implies mocked behavior is live.
- Upload as unlisted or public and test the link in a logged-out browser.
- If the portal never asks for a video URL, link it from the submission PR description as optional judge evidence rather than adding a nonstandard required file.
