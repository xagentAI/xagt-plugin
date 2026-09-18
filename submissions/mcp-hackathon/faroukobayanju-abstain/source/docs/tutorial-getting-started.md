# Build your first verifiable evaluation

In this tutorial you will start Abstain in offline replay mode, evaluate a proposed BTC trade, inspect the resulting receipt, and verify the complete evidence chain. You need no Nexus account, API key, or Redis instance.

## What you will need

- Node.js with npm
- `curl`
- `jq` for readable JSON output
- A clone of this repository

## Step 1: Install and verify the project

From the repository root:

```bash
npm ci
npm test
npm run typecheck
npm run build
```

The test command should report 168 passing tests across five files. The final two commands should exit without errors.

## Step 2: Start the replay server

```bash
ABSTAIN_WRITE_KEY=local-test-key \
COMMIT_SHA="$(git rev-parse HEAD)" \
ABSTAIN_NOW=1789689600000 \
npm run dev
```

The server prints:

```text
abstain listening on http://localhost:3000
```

Leave this terminal running. Replay mode reads committed fixtures from `fixtures/`; the receipt store lives only in this Node.js process.

## Step 3: Check identity and dependencies

Open another terminal in the repository and run:

```bash
curl -s http://localhost:3000/health | jq
curl -s http://localhost:3000/v1/ready | jq
```

`/health` should return `status: "ok"`, the project slug, and the commit you supplied. Local `/v1/ready` should return a `503` response body like this:

```json
{
  "ready": false,
  "nexus": true,
  "store": true,
  "durable": false,
  "warning": "receipts are in-process only and reset on cold start; configure Redis"
}
```

That result is expected locally. It confirms that replay data and the memory store work while clearly warning that receipts will disappear when the process stops.

## Step 4: Evaluate a proposal

```bash
curl -s -X POST http://localhost:3000/v1/evaluate \
  -H 'content-type: application/json' \
  -H 'x-abstain-key: local-test-key' \
  -d '{"symbol":"BTC/USDT","side":"BUY","notional":15000,"policy":"strict"}' | jq
```

The committed BTC fixture currently contains a `HOLD` signal, so the response should contain:

```json
{
  "verdict": "NO_TRADE",
  "policy": "strict",
  "checks": [],
  "receipt": {
    "seq": 1,
    "hash": "sha256:...",
    "prev_hash": "sha256:0000..."
  },
  "reason": "strategy signal is HOLD; no trade proposed, so no gating required"
}
```

`NO_TRADE` is a successful product result, not an error. Nothing was proposed by the strategy, so Abstain records that fact without running the ten pre-trade checks.

## Step 5: Inspect and verify the evidence

```bash
curl -s http://localhost:3000/v1/receipts | jq
curl -s http://localhost:3000/v1/verify | jq
```

The receipts response should contain the evaluation you just made. Verification should return:

```json
{
  "ok": true,
  "length": 1,
  "head": "sha256:..."
}
```

Call `/v1/evaluate` again and verify once more. The second receipt should have `seq: 2`, its `prev_hash` should equal receipt 1's `hash`, and `/v1/verify` should report `length: 2`.

## What you built

You ran the same evaluation pipeline used by the deployed API:

```text
Nexus evidence -> deterministic gate -> sealed receipt -> append-only chain -> verification
```

Continue with the [testing and deployment guide](how-to-test-and-deploy.md), or use the [API reference](reference-api.md) to explore every endpoint.

## Troubleshooting

### `401 unauthorized`

Make sure the server and request use the same `ABSTAIN_WRITE_KEY`. The write endpoint fails closed when the key is missing or empty.

### `/v1/ready` returns 503 locally

This is expected when `durable:false`. Local replay uses `MemoryStore`; only production requires Redis-backed durability.

### The receipt sequence starts above 1

The server process already handled earlier evaluations. Stop and restart it to reset the local in-memory chain.

### `curl: (7) Failed to connect`

Keep `npm run dev` running in the first terminal and issue curl commands from a second terminal.
