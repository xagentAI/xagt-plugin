# Operating proof and failure contract

This document defines what a reviewer or agent can verify without credentials.

## Version binding

A review deployment is valid only when all three surfaces agree on one exact 40-character source commit:

1. the declared review commit in the submission package;
2. `GET /health` → `status: ok|healthy` plus that commit;
3. `GET /.well-known/xagent-verification.json` → the BHRIGU slug plus that commit.

A mismatch is a release blocker, not a warning.

## Deterministic source gate

`npm run check` executes four suites:

- original acceptance behavior;
- temporal-window behavior;
- MCP protocol/tool behavior;
- immutable-artifact and authority-boundary integrity.

CI then boots the HTTP server and performs live local HTTP/MCP smoke checks, including modern `server/discover`, `tools/list`, and a temporal-window tool call.

## Public runtime dependencies

BHRIGU reads public Binance Spot BTCUSDT market data and public Bitcoin tip-height evidence from mempool.space. No API key, wallet, user account, or private credential is required.

## Failure contract

- Market data unavailable → fail closed; do not fabricate a live comparison.
- Protocol-height source unavailable → expose the unavailable state; do not silently substitute a private value.
- Invalid/unknown temporal window → structured `WINDOW_NOT_FOUND` tool error.
- Malformed modern MCP metadata → JSON-RPC `-32602`.
- MCP header/body mismatch → `-32020`.
- Unsupported MCP revision → `-32022` with requested/supported versions.
- No MCP call writes evidence or changes a precommit.

## Operating boundary

The service is intentionally narrow: public Bitcoin temporal evidence for agents. Trading, order placement, wallet access, payment, transfer, withdrawal, credentials, private account data, ORION internals, private prompts, private evaluators, and unpublished research methods remain outside this artifact.

## Reviewer challenge

A reviewer can challenge the service by asking it to:

1. expose the frozen `SEP_10_2026` record and its integrity hash;
2. compare that record with live Bitcoin reality;
3. expose `SEP_17_2026` as the next precommitted window;
4. reject a malformed MCP envelope or unsupported version;
5. prove the running review deployment is bound to the exact declared commit.

If any one of these fails, the first-place upgrade is not release-ready.
