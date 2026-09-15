# BHRIGU Bitcoin Research State API

A bounded, read-only Bitcoin research capability built for the X-Agent Open Innovation track.

It turns public Bitcoin evidence into one agent-callable research-state object:

`FIELD → WINDOW → REALITY → MEMORY`

## What it returns

- live Binance Spot BTCUSDT market state;
- Bitcoin protocol-time coordinates;
- source and freshness evidence;
- the precommitted Sep 10, 2026 observation boundary;
- current-vs-baseline delta;
- explicit confirmation/invalidation phase;
- zero trading, wallet, payment, transfer, or private-account authority.

## API

`GET /v1/state`

Optional query: `?symbol=BTCUSDT`.

`GET /health`

Returns the exact deployed Git commit.

`GET /.well-known/xagent-verification.json`

Returns the X-Agent slug and exact deployed Git commit.

## Local run

Requires Node.js 22+.

```bash
npm test
npm start
curl http://localhost:3000/v1/state
```

No API key or account credential is required.

## Public data dependencies

- Binance public Spot 24h ticker for BTCUSDT.
- mempool.space public Bitcoin tip-height endpoint.

If the Binance market source is unavailable, the capability fails closed instead of fabricating a live state. Protocol tip-height failure is exposed as unavailable while the frozen protocol epoch metadata remains explicit.

## IP boundary

This repository contains only the bounded public adapter and its frozen public research record. It does not contain ORION, private prompts, planners, evaluators, private corpora, unpublished reconstruction logic, credentials, account state, wallet code, payment code, or trading execution.

See `IP_BOUNDARY.md`.

## License / rights

No general open-source license is granted by this repository. Any future X-Agent hackathon submission will use only the explicit rights declaration required for the submitted public artifact.
