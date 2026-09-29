# Verification evidence

Every step below is runnable by a reviewer with no OlaXBT account and no API key.

## Prerequisites

- Review commit: `4dc1509ba188d3c45c800f2ac98f0b8a62a15311`
- API base URL: `https://x-agent-six.vercel.app/v1`
- Authentication: reads need none. The single write endpoint needs `X-ABSTAIN-KEY: abstain-review-4be3c5d8359c582e` — a **demo write credential published deliberately** so reviewers can exercise the capability. It grants exactly one ability: appending a receipt to a public, append-only chain. It is not a Nexus credential and cannot read, trade, or move anything.

## 1. Health check

```bash
curl --fail --silent --show-error https://x-agent-six.vercel.app/health
```

Expected response:

```json
{"status":"ok","service":"faroukobayanju-abstain","commit":"4dc1509ba188d3c45c800f2ac98f0b8a62a15311","commit_reviewable":true}
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
{"schemaVersion":1,"slug":"faroukobayanju-abstain","commit":"4dc1509ba188d3c45c800f2ac98f0b8a62a15311","commit_reviewable":true}
```

## 3. Capability call — a refusal that names its reasons

```bash
curl --fail --silent --show-error \
  --request POST https://x-agent-six.vercel.app/v1/evaluate \
  --header 'content-type: application/json' \
  --header 'x-abstain-key: abstain-review-4be3c5d8359c582e' \
  --data '{"symbol":"BTC/USDT","side":"BUY","notional":15000,"policy":"strict"}'
```

Real response captured from the deployed service, abridged to 3 of the 11 checks
(the full body contains all eleven, each with its observed value and threshold):

```json
{
  "verdict": "ABSTAIN",
  "policy": "strict",
  "policy_hash": "sha256:8fe17ed8f4c036ee52794c8790a1eef7e6a12131cc747d2a9855cce9eced3490",
  "as_of": "2026-09-18",
  "checks": [
    {
      "id": "SIGNAL_SUPPORT",
      "verdict": "FAIL",
      "observed": "HOLD",
      "threshold": "BUY",
      "unit": null,
      "source": {
        "call": "get_strategy_signal",
        "outcome": "ok"
      },
      "reason": "strategy signals HOLD; no directional signal backs a BUY",
      "detail": {
        "trade_intent": "HOLD",
        "proposed_side": "BUY",
        "confidence": 0.0508
      }
    },
    {
      "id": "NOT_QUALIFIED",
      "verdict": "FAIL",
      "observed": "NOT_QUALIFIED",
      "threshold": "QUALIFIED_FOR_OKX_LISTING",
      "unit": null,
      "source": {
        "call": "get_strategy_metrics",
        "outcome": "ok"
      },
      "detail": {
        "sharpe_ratio": {
          "observed": 0.2989,
          "gate": "> 2.0",
          "pass": false
        },
        "trading_period_days": {
          "observed": 90,
          "gate": "> 30",
          "pass": true
        },
        "estimated_aum_usdt": {
          "observed": 100000,
          "gate": "> 10000",
          "pass": true
        }
      }
    },
    {
      "id": "CORRELATED_CLUSTER",
      "verdict": "PASS",
      "observed": 1,
      "threshold": 2,
      "unit": "positions",
      "source": {
        "call": "get_strategy_trades",
        "outcome": "ok"
      },
      "detail": {
        "direction": 1,
        "concurrent_symbols": [],
        "symbol_exposure_pct": 15
      }
    }
  ],
  "receipt": {
    "seq": "<n>",
    "hash": "sha256:<...>",
    "prev_hash": "sha256:<...>"
  },
  "reason": "SIGNAL_STALE, SIGNAL_SUPPORT, NOT_QUALIFIED, DATA_GAP, DUPLICATE"
}
```

Three things a reviewer can check from this alone:

- **`SIGNAL_SUPPORT` fails** because the live strategy emits `HOLD`. Abstain gates what an
  agent *proposes*, so a proposal with no directional signal behind it is refused rather
  than waved through.
- **`NOT_QUALIFIED` names the failing sub-gate**, not a bare boolean: `sharpe_ratio`
  0.2989 against the published `> 2.0`, while the other two gates pass.
- **`CORRELATED_CLUSTER` passes** and still appears. Every check is recorded on every
  evaluation, because a receipt that stopped at the first failure would hide the limits.

Swap `"policy":"strict"` for `"permissive"` and `NOT_QUALIFIED` is skipped instead,
producing a different `policy_hash` on the same signal.

## 4. The closer — recompute the chain yourself

```bash
curl --fail --silent --show-error https://x-agent-six.vercel.app/v1/verify
```

```json
{"ok":true,"length":75,"head":"sha256:dae307b243c60e174be351b9fc9d94ebae33163e4324d258adab96bac9a9efaa"}
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

Expected: **168 tests passing across 5 files.** `NEXUS_MODE` defaults to `replay`, so
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
