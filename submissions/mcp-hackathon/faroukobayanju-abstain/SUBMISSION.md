# Abstain

A pre-trade execution gate for OlaXBT Nexus strategies. Every decision, including
every refusal, becomes a hash-chained receipt that a stranger can replay.

## Capability

- **One-line description:** An agent submits a proposed trade against a Nexus strategy signal; Abstain runs eleven deterministic pre-trade checks and returns `EXECUTE`, `ABSTAIN`, or `NO_TRADE` with a hash-chained receipt naming every check, its observed value, and its threshold.
- **Who it helps:** Any agent or desk that can place orders from a strategy signal but cannot currently prove *why* a given order was allowed, what conditions would have stopped it, or that the track record it advertises was not assembled after the fact.
- **Capability boundary:** Abstain **authorizes and refuses**. It never places an order, never holds custody, never moves funds, and never signs a transaction. It reads a Nexus strategy's published record and public market series, applies a versioned policy, and writes an append-only receipt. It is pre-trade execution control and settlement evidence for a trading strategy — not wallet risk scoring, not security monitoring, not compliance analysis.

### Why Nexus is load-bearing

Remove OlaXBT Nexus and there is no product. `get_strategy_signal` is the proposal;
`get_strategy_metrics` supplies `QUALIFIED_FOR_OKX_LISTING`, which exists nowhere
else; `get_strategy_equity` and `get_strategy_trades` supply the strategy's own
record; and the point-in-time `as_of` historical series are what make a decision
re-fetchable rather than merely asserted.

Nexus ships its own internal `Risk Gate` node, and Abstain is not a duplicate of it.
That gate is internal, pre-signal, and invisible: it enforces position and leverage
limits inside the strategy and halts on drawdown, producing no external artifact.
Abstain sits **outside**, after `get_strategy_signal`, and emits a receipt anyone can
recompute. They are complementary by construction — Abstain's thresholds sit inside
Nexus's, so Abstain refuses and records evidence before Nexus silently halts.

## Live API

- **API base URL:** `https://x-agent-six.vercel.app/v1`
- **Health-check URL:** `https://x-agent-six.vercel.app/health`
- **Authentication:** Reads are fully public and require no credential — a chain only a privileged caller can inspect is not evidence. The single write (`POST /v1/evaluate`) requires `X-ABSTAIN-KEY`; the reviewer demo key is in `verification/README.md` and is a demo credential, not a secret.
- **Rate limits / known limits:** Authenticated writes are limited to 20 evaluations per client per minute, with a separate 200-per-minute global safety ceiling in the durable Redis store, which bounds how quickly the public demo key can grow the append-only chain. An evaluation issues up to seven Nexus calls in parallel behind a 60-second TTL cache; the per-call timeout is 10s with a per-error-class retry budget. Nexus itself limits concurrent backtests (HTTP 429).
- **API contract:**

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| GET | `/health` | none | liveness + review commit (no external dependencies) |
| GET | `/.well-known/xagent-verification.json` | none | deployment proof |
| POST | `/v1/evaluate` | `X-ABSTAIN-KEY` | gate a proposed trade, append a receipt |
| GET | `/v1/receipts?from=&to=` | none | list receipts |
| GET | `/v1/receipts/:seq` | none | one receipt |
| GET/POST | `/v1/verify` | none | recompute the chain from genesis |
| GET | `/v1/policy?policy=strict\|permissive` | none | active thresholds + policy hash |
| GET | `/v1/ready` | none | dependency probe (no gate reads this) |

### The eleven checks

| # | Check | Refuses when | Source |
| --- | --- | --- | --- |
| 1 | `SIGNAL_STALE` | signal older than `max_signal_age_s` | `get_strategy_signal` |
| 2 | `SIGNAL_SUPPORT` | the strategy signal does not back the proposed side (a `HOLD` backs nothing) | `get_strategy_signal` |
| 3 | `NOT_QUALIFIED` | metrics status ≠ `QUALIFIED_FOR_OKX_LISTING` | `get_strategy_metrics` |
| 4 | `FUNDING_REGIME` | funding rate beyond threshold **and against** the proposed side | `get_historical_funding` |
| 5 | `OI_SHOCK` | one-day open-interest move exceeds `max_oi_delta_pct` | `get_open_interest` |
| 6 | `DRAWDOWN_BUDGET` | equity drawdown from peak exceeds `max_drawdown_pct` | `get_strategy_equity` |
| 7 | `CORRELATED_CLUSTER` | concurrent same-direction positions reach `max_cluster_size` | `get_strategy_trades` |
| 8 | `LOSS_STREAK` | trailing consecutive losers reach `max_loss_streak` | `get_strategy_trades` |
| 9 | `DATA_GAP` | any required datum absent or unfetchable, or `as_of` outside coverage | `get_historical_coverage` |
| 10 | `SIZE_BOUND` | notional outside `[min_notional, max_notional]` | request |
| 11 | `DUPLICATE` | `signal_id` already committed to the chain | receipt chain |

All eleven run on every evaluation. There is no bypass: Abstain gates what an agent
**proposes**, not what the strategy happens to be emitting, so a proposal with no
directional signal behind it fails `SIGNAL_SUPPORT` and the verdict is `ABSTAIN` with all
eleven checks recorded. A receipt that stopped at the first failed check would hide the
remaining limits, and the limits are the evidence.

Receipts 1-70 in the live chain carry a legacy `NO_TRADE` verdict with an empty `checks`
array, written before 2026-09-18 when a `HOLD` signal short-circuited the gate. They
remain valid chain links and verify normally; the change is visible in the record rather
than erased from it.

## Source and reproducibility

- **Source repository:** `https://github.com/faroukobayanju/abstain`
- **Review commit:** `4dc1509ba188d3c45c800f2ac98f0b8a62a15311`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm test` — 168 tests, no API key and no network required
- **Run locally:** `npm run build && COMMIT_SHA=$(git rev-parse HEAD) ABSTAIN_WRITE_KEY=demo-key npm start`
- **Deploy:** Vercel git integration; `vercel.json` rewrites all paths to `api/index.ts`. Set `ABSTAIN_WRITE_KEY`, `NEXUS_API_KEY` + `NEXUS_MODE=live`, and either `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN` or Vercel's `KV_REST_API_URL` + `KV_REST_API_TOKEN`. Production evaluations refuse to run without durable storage.
- **Version binding:** `/health` reports `VERCEL_GIT_COMMIT_SHA` in the body and in the `x-source-commit` response header. It has **zero external dependencies** by design: coupling a hard gate to Nexus or Redis uptime would let a third party fail a gate already passed.

```json
// GET /health
{"status":"ok","service":"faroukobayanju-abstain","commit":"<40-character commit SHA>","commit_reviewable":true}
```

```json
// GET /.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"faroukobayanju-abstain","commit":"<40-character commit SHA>","commit_reviewable":true}
```

## Verification

Reproducible calls and redacted responses are in `verification/README.md`.

- **Health-check result:** `200` with `status: ok` and the exact review commit.
- **Capability call:** `POST /v1/evaluate` with `{"symbol":"BTC/USDT","side":"BUY","notional":15000}`.
- **Expected error behavior:** missing/incorrect `X-ABSTAIN-KEY` → `401` naming the header. Malformed input → `400` naming the offending field. Nexus unreachable → **`ABSTAIN` with `DATA_GAP`, never `EXECUTE`**. Receipt store unreachable → `503` with `receipt_written: false`, never a verdict the chain cannot back.

## Evidence

All figures below come from strategy `str_515920d047ca`, backtest run
`bt-7a0daf243c06` (19 trades, 91 equity points, 2026-06-19 → 2026-09-17), retrieved
from Nexus and committed under `source/fixtures/`.

### 1. The strategy does not qualify, and exactly one gate fails

`catalog.json` publishes the listing gates. Live `get_strategy_metrics` returns:

| Gate | Threshold | Observed | |
| --- | --- | --- | --- |
| `sharpe_ratio` | > 2.0 | 0.2989 | ✗ |
| `trading_period_days` | > 30 | 90 | ✓ |
| `estimated_aum_usdt` | > 10000 | 100000 | ✓ |

Check #2 names the failing sub-gate rather than returning a bare boolean. Because a
standing refusal would leave no `EXECUTE` path at all, `require_qualified` is the one
key that differs between the `strict` and `permissive` policies. The published policy
endpoint exposes two distinct `policy_hash` values without weakening replay protection.

### 2. A refusal derived from a real loss

The first three trades of the run entered on the same bar:

```
ETH/USDT  dir 1  lev 3.0  entry_bar 50  stop_loss  pnl -1836.37  pnl_pct -25.38
BTC/USDT  dir 1  lev 3.0  entry_bar 50  stop_loss  pnl -1701.73  pnl_pct -25.38
SOL/USDT  dir 1  lev 3.0  entry_bar 50  stop_loss  pnl -1857.04  pnl_pct -25.38
```

Three correlated 3x longs opened together and stopped out together for **-5,395**.
The equity curve confirms the consequence: peak 101,538.70 → trough 93,799.53 =
**-7.62%**, exactly the `max_drawdown` Nexus reports. A single-symbol exposure cap
passes all three, because no single position breaches 25%. Check #6 exists because of
this, not in spite of it.

### 3. The threshold frontier — published in full

`docs/evidence/frontier.txt`. Every row replays all 19 trades through the same
`runGate()` the live API calls, varying one threshold:

```
  SETTING                        TAKEN  REFUSED       PNL   MAX DD
  no gate (every check off)         19        0   1845.52    5.40%
  max_cluster_size = 2               3       16   2633.02    1.53%
  max_cluster_size = 3               7       12   -921.71    3.84%
  max_cluster_size = 4              16        3  -1429.55    5.60%
  max_drawdown_pct = 3              15        4  -5287.89    7.30%
  max_drawdown_pct = 5              16        3  -2963.50    5.40%
  max_loss_streak = 2               14        5  -3532.13    5.40%
  max_loss_streak = 3               15        4  -5089.11    6.17%
  shipped policy (all checks)        1       18  -1556.98    1.56%
```

**This is published in full, including the rows that do not flatter the shipped
policy.** Read honestly:

- `CORRELATED_CLUSTER = 2` dominates on both axes: better pnl **and** lower drawdown than taking every trade. It is also the only check with a structural argument independent of this sample — three simultaneous correlated 3x longs are one bet placed three times.
- `DRAWDOWN_BUDGET` and `LOSS_STREAK` **cost return** on this sample, and together they pull the shipped policy below the no-gate baseline.
- The shipped policy executes 1 of 19 trades. With n=1 the pnl figure carries no statistical content in either direction. The drawdown improvement (5.40% → 1.56%) is the defensible claim.

**We did not retune.** Re-fitting thresholds to 19 trades until the backtest flatters
the product is precisely the behaviour this product exists to make visible. The policy
ships as committed, the frontier ships beside it, and `GET /v1/policy` plus
`policy_hash` let any operator adopt a different setting and prove which rules applied.

## Security and data handling

- **Data collected:** None from callers beyond the request body (`symbol`, `side`, `notional`, optional `policy`). Signal identity is derived server-side from Nexus and cannot be overridden by callers. No personal data, no accounts, no cookies.
- **Purpose and retention:** Receipts are retained indefinitely by design — an append-only evidence chain whose records can be deleted is not evidence.
- **Third parties / outbound network calls:** OlaXBT Nexus MCP (`nexus.olaxbt.xyz`) and, when configured, Upstash Redis REST. No others.
- **Secrets:** No secrets are committed. `.gitignore` excludes `.env*`; the repository contains no `nxk_` value. `NEXUS_API_KEY` is server-side only and never appears in a response. The `X-ABSTAIN-KEY` published for review is a demo write credential, deliberately disclosed.
- **Known risks / restrictions:** Abstain has no custody and cannot move funds. Its verdicts are policy evaluations against a specific strategy's published record; they are not investment advice. `max_oi_delta_pct` is a starting value, not a calibrated one, and is labelled as such in `policy.base.json`. The equity series is 30–120 daily points, so `DRAWDOWN_BUDGET` is a coarse estimate — the receipt reports `sample_count` rather than implying precision it does not have.

## Support

- **Team / builder:** faroukobayanju
- **Contact:** `https://github.com/faroukobayanju`
