# Spending Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace repeated funding signing links with a production-oriented spending authorization that lets Hermes fund approved venues within a user-defined cap.

**Architecture:** `clink-core` owns the authorization ledger, policy checks, native funding settlement, and audit-friendly receipts. Vertical adapters such as `clink-prediction-markets` resolve venue targets and call core to spend from an active authorization; they should not ask Hermes to send users to per-transfer signing pages.

**Tech Stack:** Python/FastAPI services, FastMCP, JSONL demo persistence, Polygon USDC, Clink Native Facilitator.

## Global Constraints

- Users bind wallets and Polymarket in the account page, then authorize a spending cap once.
- Hermes can spend only within active cap, per-order limit, venue, token, chain, and expiry.
- Old `/funding/signing-console/*` and `/funding/x402/payment-console/*` are removed from the product/API surface.
- Native funding settlement must use `X402_PAYMENT_TOKEN_NAME=USD Coin` for Polygon native USDC.
- Dashboard remains read-only for trading and funding state.

---

### Task 1: Core Spending Authorization

**Files:**
- Modify: `services/funding_service/schemas.py`
- Modify: `services/funding_service/service.py`
- Modify: `services/funding_service/app.py`
- Modify: `mcp_servers/funding_server.py`
- Modify: `shared/config.py`
- Test: `scripts/funding_spending_authorization_unit_smoke.py`

**Interfaces:**
- Produces: `POST /funding/spending-authorizations`, `GET /funding/spending-authorizations/{id}`, `POST /funding/spending-authorizations/{id}/spend`, `POST /funding/spending-authorizations/{id}/revoke`.
- Produces MCP tools: `create_spending_authorization`, `spend_from_spending_authorization`, `revoke_spending_authorization`.

- [ ] Write a smoke test that creates an active spending authorization and spends from it.
- [ ] Verify the smoke fails before implementation.
- [ ] Add schemas and service methods.
- [ ] Add FastAPI and MCP endpoints.
- [ ] Verify the smoke passes.

### Task 2: Prediction Markets Uses Core Authorization

**Files:**
- Modify: `mcp_servers/prediction_markets_server.py`
- Modify: `dashboard_frontend/src/App.jsx`
- Modify: `README.md`
- Test: `scripts/fund_from_spending_authorization_mcp_unit_smoke.py`

**Interfaces:**
- Produces MCP tool: `fund_polymarket_from_spending_authorization`.
- Removes `create_clink_funding_signing_link` and `create_polymarket_funding_transfer_link` from the production tool surface.

- [ ] Write/update a smoke test that calls the new spend-from-authorization flow.
- [ ] Verify the smoke fails before implementation.
- [ ] Add the new MCP tool and route it to core.
- [ ] Update dashboard copy to “spending cap authorization” instead of repeated signing links.
- [ ] Verify smoke and UI build.

### Task 3: Product Cleanup

**Files:**
- Modify: both `README.md` files.
- Modify: `.env.example` files if config names change.

**Interfaces:**
- Public product flow becomes: bind wallet -> bind Polymarket -> authorize cap -> Hermes scans/funds/trades within cap -> dashboard tracks results.

- [ ] Remove old signing-link flow from primary documentation.
- [ ] Remove legacy endpoint documentation and keep spending authorization as the only funding path.
- [ ] Run targeted smoke tests in both repos.
