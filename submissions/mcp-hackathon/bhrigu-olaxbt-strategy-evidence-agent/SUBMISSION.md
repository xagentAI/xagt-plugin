# BHRIGU OlaXBT Strategy Evidence Agent

## Judge-first review path

**OLAXBT STRATEGY = CREATED + BACKTESTED + NEXUS VALIDATED.**

**APPLICATION = DISTINCT AGENT/MCP APPLICATION.** This submission is not strategy-only, not backtest-only, and not a simple API wrapper. The application consumes four live OlaXBT Nexus evidence surfaces and exposes one bounded REST capability plus one read-only MCP tool for agent review.

**Primary job:** Can an agent trust the evidence context behind this OlaXBT strategy signal right now?

Verified BTC/USDT strategy evidence from the live Nexus-backed review deployment:

- Sharpe: **1.7668**
- Win rate: **52.94%**
- Profit factor: **1.6494**
- Max drawdown: **0.31%**
- Trades: **17**
- Four Nexus sources: **signal + metrics + trades + equity**

**Authority boundary:** **OLAXBT = strategy + signal authority. BHRIGU = evidence interpretation layer.** BHRIGU does not create a second BUY/SELL/HOLD signal, forecast price, place orders, execute trades, access wallets, or move funds.

**Confidence epistemic boundary:** the raw OlaXBT confidence value is preserved as source evidence. BHRIGU does **not** invent a confidence threshold, calibration rule, or trading judgment from that value unless OlaXBT explicitly defines those semantics.

## Capability

- **One-line description:** A read-only evidence interpretation layer around the current OlaXBT BTC/USDT strategy signal, combining the observed signal with strategy metrics, recent trades, equity context, contradictions, limitations, and source status.
- **Who it helps:** AI agents and research systems that need to decide how much trust to place in the evidence context around an OlaXBT strategy signal without delegating trading authority.
- **Capability boundary:** **OLAXBT = strategy + signal authority. BHRIGU = evidence interpretation layer.** BHRIGU does not create a second BUY/SELL/HOLD signal, forecast price, place orders, execute trades, access wallets, or move funds.

## Live API

- **API base URL:** https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app
- **Health-check URL:** https://bhrigu-bitcoin-research-state-rn4vpiwc8-aibhrigus-projects.vercel.app/health
- **Authentication:** no caller credential. The OlaXBT Nexus credential is server-side only.
- **Rate limits / known limits:** `BTC/USDT` only in this bounded trading-track slice; upstream OlaXBT availability and limits apply; each Nexus tool call has a 15-second timeout; no SLA is claimed.
- **API contract:** REST `POST /v1/strategy-evidence` with `{"symbol":"BTC/USDT"}`; MCP `POST /mcp` tool `bhrigu_get_olaxbt_strategy_evidence` with the same symbol. Both return the same bounded Strategy Evidence object.

## Source and reproducibility

- **Source repository:** https://github.com/AiBhrigu/bhrigu-bitcoin-research-state-api
- **Review commit:** `d29423daf121a4318dec063d0694b5fec8eb2ed3`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm test`
- **Run locally:** `npm ci && npm start`; live OlaXBT calls require the authorized `OLAXBT_NEXUS_API_KEY` only in the server environment.
- **Deploy:** deploy exact review commit with Node.js 22+ and bind the Nexus credential server-side.
- **Version binding:** `/health` and `/.well-known/xagent-verification.json` expose the exact deployed commit; the verification endpoint also exposes this trading-track slug.

The deployed health response is:

```json
{"status":"ok","commit":"d29423daf121a4318dec063d0694b5fec8eb2ed3"}
```

The deployment proof is:

```json
{"schemaVersion":1,"slug":"bhrigu-olaxbt-strategy-evidence-agent","commit":"d29423daf121a4318dec063d0694b5fec8eb2ed3"}
```

## Verification

Repeatable REST and MCP calls plus redacted proof are in `verification/README.md`.

- **Health-check result:** HTTP 200, exact review commit.
- **REST capability call:** HTTP 200 with all four OlaXBT `source_status.*.ok=true`.
- **MCP capability call:** HTTP 200; `structuredContent` is the same Strategy Evidence object.
- **Expected error behavior:** unsupported symbols fail explicitly; missing or failed upstream evidence is surfaced and never fabricated.

## Security and data handling

- **Data collected:** only requested symbol; no user identity, wallet, payment, account, or credential data.
- **Purpose and retention:** transient evidence interpretation; no request persistence by this capability.
- **Third parties / outbound network calls:** OlaXBT Nexus MCP for strategy signal, metrics, trades, and equity. The inherited Bitcoin Temporal Evidence capability also uses public Binance and mempool.space data.
- **Secrets:** no real secret is committed or returned. Nexus credential remains server-side only.
- **Known risks / restrictions:** historical performance is context, not forecast; source availability can limit output; `assessment` is not an order instruction.

## Support

- **Team / builder:** BHRIGU / AiBhrigu
- **Contact:** https://x.com/bhrigu_io
- **License / rights:** no general open-source license is granted; X-Agent review/archive rights for this bounded artifact are declared in `RIGHTS.md`.
