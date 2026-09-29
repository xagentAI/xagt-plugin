# Multi-model review input: Leo Labs OKX.AI services (#3977)

Date: 2026-07-07
Reviewer question: If a buyer agent or human browses OKX.AI and sees these 4 services, how credible are they? Is pricing fair? What should change before first public tweet + Hackathon?

## Seller context

- ASP: Leo Labs, Agent ID 3977, 0 sales, approvalStatus listed (avatar update under re-review)
- Seller: solo INTJ builder, Polymarket quant + AI workflow, has PolyData asset (not fully exposed in APIs yet)
- Strategy: cheap option on OKX.AI + build in public + Genesis Hackathon (deadline 2026-07-17)
- Payment: x402 enabled on production — **unpaid POST returns HTTP 402, 1 USDT per call** (amount 1000000 atomic, 6 decimals)

## Listed services (all 1 USDT listing fee)

### 1. World Cup Smart Money Radar
- Endpoint: POST https://api.leolabs.me/world-cup-smart-money-radar
- Claims: tracks profitable World Cup PM wallets, position changes, side, notional, confidence
- Implementation: LIVE — scans Polymarket Gamma (world-cup tag) + data-api trades (takerOnly, min $500) + lb-api 7d profit + positions enrichment. Max 3 markets scanned per call, 120s cache.
- Caveats in code: heuristic, can be wrong/stale, not investment advice
- Competition: WorldCupCaller 166 sales @ 0.5 USDT, World Cup Alpha 52 @ ?, AlphaCopy 171 @ 0.1 (PM smart money leader)

### 2. Polymarket Smart Money Radar
- Endpoint: POST https://api.leolabs.me/polymarket-smart-money-radar
- Claims: all-market PM smart money, same signal shape as W1
- Implementation: LIVE — same pipeline as W1 but market discovery via public-search / volume fallback
- Competition: RED OCEAN — AlphaCopy, SentryX, multiple "聪明钱" ASPs

### 3. Agent Delivery Audit Gate
- Endpoint: POST https://api.leolabs.me/agent-delivery-acceptance-audit
- Claims: audits agent task delivery vs goal/artifacts/validation → pass/needs_review/fail
- Implementation: LIVE — **deterministic rule-based auditor** (regex flags, scoring dimensions), NOT an LLM judge. Good for hard-gate detection, dispute triage. Open-source project: agent-acceptance-gate
- Competition: CertiK 53 sales (security), GenLayer (disputes). Few direct "delivery acceptance" competitors on marketplace
- Unique angle: agent marketplace QA / escrow safety layer

### 4. Event Price Divergence Radar
- Endpoint: POST https://api.leolabs.me/event-price-divergence-radar
- Claims: PM event probability 24h move vs OKX spot 24h momentum → divergence signals
- Implementation: LIVE — Gamma public-search per asset + OKX v5 ticker, thresholds prob 2% vs spot 0.3%
- Competition: **named divergence niche largely empty**; adjacent OnChain Arb Scout 145 sales @ 0.1

## Marketplace benchmarks (2026-07-07 scan)

- 358 ASPs, 675 service slots, ~2982 cumulative orders, ~$777 rough GMV
- ~78% ASPs zero sales
- Fee median ~0.08 USDT; data APIs often 0.01-0.1; signal/report类 0.1-1
- Our 4 services all at **1 USDT** — internal research already flagged as **expensive vs competitors**

## Technical risks buyers might notice

1. **Pay-before-try**: x402 wall — no free sample call on listed endpoints (buyer must pay 1 USDT to see output quality)
2. **Smart money definition**: "profitable" = leaderboard 7d PnL + large taker trades heuristic, not verified on-chain PnL audit
3. **Scan limits**: only 3 PM markets per radar call — may miss user's topic
4. **Audit gate limits**: rule-based, English-centric patterns; not full code review or legal/compliance
5. **No on-listing proof**: listing descriptions can't include URLs to GitHub or sample JSON
6. **Category mismatch?**: Agent listed under SOFTWARE_SERVICES but 3/4 are finance data signals

## Not yet listed but deployed live on same host

- Crypto Market Regime Radar, World Cup Upset Alert (also 1 USDT x402)

## Review tasks

For each of the 4 listed services, please answer:
1. **Buyer first impression** (1-2 sentences): trustworthy / skeptical / confused?
2. **Product-market fit** on OKX.AI today: high / medium / low — why?
3. **Pricing verdict**: keep 1 USDT / lower to X / free tier — with competitor anchor
4. **Top credibility gap** and **one fix** (listing copy, price, free sample, product scope, or kill)

Then synthesize:
- Which 1-2 services to lead with in tweet + Hackathon demo
- Recommended price table for all 4
- Any service to pause/rename/reposition before public launch
- Overall: 可继续 / 修改后继续 / 停止扩服务先修核心

Be blunt. Leo prefers truth over ego. Platform GMV is tiny (~$800) — this is reputation + optionality play, not revenue yet.
