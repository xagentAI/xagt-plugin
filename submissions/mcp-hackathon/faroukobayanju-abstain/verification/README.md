# Verification evidence

Every step below is runnable by a reviewer with no OlaXBT account and no API key.

## Prerequisites

- Review commit: `9ee86c95a9b07e0af76eec7ce68f9f8625cc3616`
- API base URL: `https://x-agent-six.vercel.app/v1`
- Authentication: reads need none. The single write endpoint needs `X-ABSTAIN-KEY: abstain-review-4be3c5d8359c582e` — a **demo write credential published deliberately** so reviewers can exercise the capability. It grants exactly one ability: appending a receipt to a public, append-only chain. It is not a Nexus credential and cannot read, trade, or move anything.

## 1. Health check

```bash
curl --fail --silent --show-error https://x-agent-six.vercel.app/health
```

Expected response:

```json
{"status":"ok","service":"faroukobayanju-abstain","commit":"9ee86c95a9b07e0af76eec7ce68f9f8625cc3616","commit_reviewable":true}
```

The same commit is also returned in the `x-source-commit` response header.

**This endpoint has no external dependencies.** It returns `200 ok` with `NEXUS_API_KEY`
unset and the receipt store unreachable — asserted by a test
(`source/test/app.test.ts`, "stays ok with NO Nexus key and a completely broken store").

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://x-agent-six.vercel.app/.well-known/xagent-verification.json
```

```json
{"schemaVersion":1,"slug":"faroukobayanju-abstain","commit":"9ee86c95a9b07e0af76eec7ce68f9f8625cc3616","commit_reviewable":true}
```

## 3. Capability call — a verifiable no-trade decision

```bash
curl --fail --silent --show-error \
  --request POST https://x-agent-six.vercel.app/v1/evaluate \
  --header 'content-type: application/json' \
  --header 'x-abstain-key: abstain-review-4be3c5d8359c582e' \
  --data '{"symbol":"BTC/USDT","side":"BUY","notional":15000,"policy":"strict"}'
```

Current success response (abridged):

```json
{
  "verdict": "NO_TRADE",
  "policy": "strict",
  "policy_hash": "sha256:e3e38d19376f77ee9...",
  "as_of": "2026-09-17",
  "reason": "strategy signal is HOLD; no trade proposed, so no gating required",
  "checks": [],
  "receipt": {"seq":1,"hash":"sha256:...","prev_hash":"sha256:0000..."}
}
```

The live strategy currently emits `trade_intent: HOLD`, so nothing was proposed,
authorized, or refused. A receipt is still written, so the chain has no gaps. When the
signal is BUY or SELL, the response contains all ten checks; the deterministic offline
suite exercises those non-HOLD paths without depending on the live signal's timing.

## 4. The closer — recompute the chain yourself

```bash
curl --fail --silent --show-error https://x-agent-six.vercel.app/v1/verify
```

```json
{"ok":true,"length":3,"head":"sha256:8cb8b2e41b38ef85f50b62c845ba1edb7c9866a4bc28f805fbfbf61a6a8046c2"}
```

Then fetch any receipt and recompute its hash independently:

```bash
curl --fail --silent --show-error https://x-agent-six.vercel.app/v1/receipts/1
```

`hash = sha256(canonical({...body, seq, prev_hash}))`, where `canonical` sorts object
keys recursively and preserves array order (`source/src/receipt/schema.ts`).

## 5. Safe failure behavior

| Call | Expected |
| --- | --- |
| `POST /v1/evaluate` with no `x-abstain-key` | `401 {"error":"unauthorized","reason":"X-ABSTAIN-KEY missing or incorrect"}` |
| `POST /v1/evaluate` with `{"symbol":"BTC"}` | `400 {"error":"bad_request","field":"symbol",...}` |
| `GET /v1/receipts/99999` | `404 {"error":"not_found","seq":99999}` |
| `GET /v1/policy?policy=loose` | `400` naming the field |
| Nexus unreachable | `200` with `"verdict":"ABSTAIN"` and `DATA_GAP` failing — **never `EXECUTE`** |
| Receipt store unreachable | `503 {"error":"store_unavailable","receipt_written":false}` |

## 6. Full offline reproduction — no key, no network

```bash
cd source && npm ci && npm test
```

Expected: **162 tests passing across 5 files.** `NEXUS_MODE` defaults to `replay`, so
the suite serves the recorded cassettes in `fixtures/` instead of calling Nexus.

The tests that carry the most weight:

| Test | Proves |
| --- | --- |
| `chain.test.ts` "two concurrent appends..." | the receipt chain cannot fork under concurrency. A hook suspends one writer between its head read and its commit — the exact interleave that forks a naive chain — and verification still passes. |
| `chain.test.ts` "names the exact sequence number of an edited receipt" | tampering with receipt 17 of 40 makes `/v1/verify` report `divergedAt: 17`, not a vague failure. Also covers a deleted record and a re-sealed record whose link no longer matches. |
| `checks.test.ts` "reproduces the reported 7.62% drawdown" | `DRAWDOWN_BUDGET` independently derives the same figure Nexus reports, from the recorded equity curve. |
| `checks.test.ts` "refuses a BTC long while ETH and SOL are open long at bar 50" | the headline refusal, on real trade data. |
| `checks.test.ts` "same signal, two policies, two verdicts" | pure policy comparison without weakening live replay protection. |
| `nexus.test.ts` "404 on a KNOWN tool is an ABSENCE" | Nexus overloads 404 for two facts; receipts keep them apart. |
| `replay.test.ts` "never shows the gate an equity point from the future" | the replay has no lookahead. A loss placed after trade 1 must not affect trade 1's verdict. |

## 7. Regenerate the evidence artifacts

```bash
cd source && npm run chart      # docs/evidence/with-without-gate.svg + replay.txt
cd source && npm run frontier   # docs/evidence/frontier.svg + frontier.txt
```

Both read the committed cassettes and call the same `runGate()` the live API calls —
not a reimplementation. Re-recording the cassettes from Nexus requires a key:

```bash
NEXUS_MODE=live NEXUS_API_KEY=nxk_... npm run record
```

## Fixture provenance

`source/fixtures/README.md` declares, per file, which cassettes are verbatim
recordings and which three are synthetic. No recorded value was altered. Every figure
quoted as evidence in `SUBMISSION.md` — sharpe 0.2989, max drawdown 7.62%, the bar-50
cluster, the frontier — comes from the recorded set and can be re-fetched from Nexus
with a key bound to strategy `str_515920d047ca`.
