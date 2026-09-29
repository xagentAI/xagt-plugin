# Multipu

## Capability

- **One-line description:** Multipu is an autonomous decentralized execution engine that aggregates top launchpads like Pump.fun, Pons, and Meteora across Solana, BNB, and Robinhood to automate liquidity deployment, trade, and unify cross-chain creator earnings. It features an embedded copilot, Multipu AI, which uses OLAXbt telemetry and the X-Agent framework to turn a single prompt into an autonomous trading and arbitrage agent.
- **Who it helps:** Autonomous AI agents, automated trading algorithms, DeFi developers, liquidity managers, and cross-chain creators seeking unified liquidity deployment and automated arbitrage across Solana, BNB, and Robinhood.
- **Capability boundary:** Aggregates real-time token launchpad telemetry (Pump.fun, Pons, Meteora, Raydium, Uniswap), compiles high-level natural language strategies into verified execution steps, and routes execution through KeeperHub and DEX liquidity pools. It does not custody user private keys without explicit client authorization, execute unapproved fund transfers, or bypass simulated slippage and MEV protection safeguards.

## Technical Description

- **Multi-Chain Launchpad Aggregation:** Multipu ingests and normalizes real-time telemetry from top token launchpads including Pump.fun, Pons, and Meteora on Solana, PancakeSwap on BNB Smart Chain, and Robinhood Web3 integrations. It tracks bonding curve progression, market depth, holder distribution, and liquidity lock metrics across chains.
- **Multipu AI Copilot and OLAXbt Telemetry:** High-level natural language trading directives and strategy prompts are parsed by Groq-accelerated models (Llama 3.3 70B Versatile) synthesized with live OLAXbt market sentiment, momentum signals, and volume divergence feeds to generate verified execution steps.
- **MEV-Protected Routing via KeeperHub:** Automated swaps and trades route through KeeperHub private mempools and on-chain DEX pools (Raydium, PancakeSwap, Uniswap). Pre-flight dry-run simulations enforce strict user-defined slippage tolerances, minimum return thresholds, and gas bounds before broadcasting transactions.
- **Agent and Developer APIs:** RESTful API endpoints allow AI agents and developers to explore live launches (`/api/launches/explore`), monitor trending volume (`/api/launches/trending`), search tokens (`/api/tokens/search`), and provision API keys (`/api/keys/generate`).

## Live API

- **API base URL:** https://www.multipu.fun/api
- **Health-check URL:** https://www.multipu.fun/api/health
- **Authentication:** None for public telemetry, launch exploration, and health inspection. Developer and agent mutations require API keys or wallet signatures.
- **Rate limits / known limits:** Requests are rate-limited to 120 calls per minute per IP address. Request bodies must be valid JSON within 256 KiB. Expected latency is under 500ms for read operations.
- **API contract:** The API directory is exposed at `GET https://www.multipu.fun/api`, health check at `GET /api/health`, launch discovery at `GET /api/launches/explore`, trending tokens at `GET /api/launches/trending`, and token search at `GET /api/tokens/search`.

## Source and reproducibility

- **Source repository:** https://github.com/wisdomdivine/multipu
- **Review commit:** `efe61edb90358463c45f901e42964aa90261723c`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npx tsc --noEmit`
- **Run locally:** `npm run dev`
- **Deploy:** Vercel deployment with Next.js App Router and Supabase persistence; set `VERCEL_GIT_COMMIT_SHA=efe61edb90358463c45f901e42964aa90261723c` and `NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA=efe61edb90358463c45f901e42964aa90261723c`
- **Version binding:** The deployed service exposes the exact 40-character review commit from `/api/health` and `/.well-known/xagent-verification.json`.

The API exposes:

```json
{"status":"ok","commit":"efe61edb90358463c45f901e42964aa90261723c"}
```

```json
{"schemaVersion":1,"slug":"wisdomdivine-multipu","commit":"efe61edb90358463c45f901e42964aa90261723c"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** HTTP 200 with status `ok` and the exact review commit.
- **Capability call:** `GET https://www.multipu.fun/api/launches/explore?limit=1` returns active real-time multi-chain launchpad telemetry and market metrics across Solana, BNB, and Robinhood.
- **Expected error behavior:** Requesting an undefined route returns HTTP 404 with JSON error `{"error":"Not Found"}`. Rate-limiting violations return HTTP 429 `{"error":"Rate limited"}`.

## Security and data handling

- **Data collected:** Public query requests and IP addresses for in-memory rate limiting only.
- **Purpose and retention:** In-memory sliding window rate limiting; telemetry discarded after the active window.
- **Third parties / outbound network calls:** Solana RPC nodes, BNB Smart Chain RPC nodes, Supabase, Groq API.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** Read-only exploration requires no authorization; execution requires client-side signing or configured agent treasury keys.

## Support

- **Team / builder:** Wisdom Divine
- **Contact:** https://github.com/wisdomdivine
- **License / rights:** MIT License. Full authorization granted for hackathon evaluation, reproduction, and archive.
