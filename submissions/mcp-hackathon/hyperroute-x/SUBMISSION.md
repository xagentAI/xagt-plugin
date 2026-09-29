# HyperRoute X

A high-performance, deterministic execution co-processor and optimal swap routing engine built specifically for AI agents transacting on X Layer (OKX Layer 2).

## Capability

- **One-line description:** Calculates mathematically optimal split routes across X Layer liquidity pools, builds raw ABI-encoded calldata, and pre-simulates execution before broadcast.
- **Who it helps:** Autonomous AI agents, algorithmic traders, DAO treasury agents, and automated portfolio managers on OKX.AI and X Layer.
- **Capability boundary:** Performs off-chain routing optimization, EVM calldata generation (Uniswap V3-compatible SwapRouter), and pre-execution eth_call simulation. It does not custody funds, sign transactions on behalf of users, or execute smart contract auditing.

## Live API

- **API base URL:** https://alexbrian3-hyperroute-x.onrender.com/api/v1
- **Health-check URL:** https://alexbrian3-hyperroute-x.onrender.com/health
- **Authentication:** None (open public endpoints for hackathon verification)
- **Rate limits / known limits:** 120 requests/minute; 10-second default RPC timeout.
- **API contract:** OpenAPI specification available at https://alexbrian3-hyperroute-x.onrender.com/docs or in `source/app/models.py`. Standard MCP schema at `/api/v1/mcp/tools`.

## Source and reproducibility

- **Source repository:** https://github.com/AlexBrian3/xagt-plugin
- **Review commit:** `e8be87499fdf6f977051fa3b2d1fb0d916322e8d`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pytest submissions/mcp-hackathon/hyperroute-x/source/tests`
- **Run locally:** `uvicorn app.main:app --host 0.0.0.0 --port 8000` (from inside `source/`)
- **Deploy:** Deploy container using `source/Dockerfile` to any container cloud (Render, Railway, Fly.io).
- **Version binding:** The service reports the review commit in the `/health` response body, the `x-source-commit` HTTP header, and the `/.well-known/xagent-verification.json` endpoint.

The API exposes:

```json
// GET https://alexbrian3-hyperroute-x.onrender.com/health
{
  "status": "ok",
  "commit": "e8be87499fdf6f977051fa3b2d1fb0d916322e8d",
  "version": "e8be87499fdf6f977051fa3b2d1fb0d916322e8d",
  "slug": "hyperroute-x",
  "network": "xlayer-mainnet"
}
```

```json
// GET https://alexbrian3-hyperroute-x.onrender.com/.well-known/xagent-verification.json
{
  "schemaVersion": 1,
  "slug": "hyperroute-x",
  "commit": "e8be87499fdf6f977051fa3b2d1fb0d916322e8d"
}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** Returns HTTP 200 with `status: ok` and the exact review commit SHA.
- **Capability call:** `POST /api/v1/quote` with `{"token_in": "OKB", "token_out": "USDT", "amount_in": "1.0", "max_slippage_bps": 50}` returning split routes, fee tiers, and guaranteed min output.
- **Expected error behavior:** Returns HTTP 400 with descriptive error detail for identical in/out tokens, negative amounts, or malformed EVM addresses.

## Security and data handling

- **Data collected:** No personal data, IP logs, or wallet private keys are recorded or stored.
- **Purpose and retention:** Ephemeral in-memory calculation; zero persistent storage.
- **Third parties / outbound network calls:** Direct JSON-RPC calls to public X Layer RPC (`https://rpc.xlayer.tech`) for pre-flight `eth_call` simulation.
- **Secrets:** No secrets or private keys are committed or used. Review access is open and public.
- **Known risks / restrictions:** Price impact estimates reflect on-chain benchmark liquidity models; live mainnet execution remains subject to block-by-block miner/sequencer ordering.

## Support

- **Team / builder:** AlexBrian3
- **Contact:** GitHub @AlexBrian3
- **License / rights:** MIT License. Authorized under the official X-Agent MCP Hackathon program terms.
