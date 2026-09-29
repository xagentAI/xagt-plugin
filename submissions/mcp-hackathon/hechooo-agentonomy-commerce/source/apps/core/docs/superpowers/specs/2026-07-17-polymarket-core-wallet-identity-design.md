# Polymarket Core Wallet Identity Design

## Goal

Make Clink Core the only wallet-identity and spending-permission authority while keeping Polymarket CLOB authorization as a separate, venue-specific action.

## Product Boundary

- Core Account binds wallet ownership, spending grants, and chain allowances once.
- Prediction Markets never creates or edits Core wallet identity or spending grants.
- The Polymarket page connects the already-bound Core wallet only to sign Polymarket CLOB authorization.
- A different connected wallet is rejected by both the browser and the Prediction Markets backend.
- Hermes relays links and status but never supplies wallet identity fields or signs on the user's behalf.

## Core Contract

`GET /internal/account-readiness?user_id=...` remains internal-token protected and adds:

```json
{
  "wallet_bound": true,
  "wallet_address": "0x...",
  "wallet_identity_id": "wallet_...",
  "spending_grant_active": true,
  "chain_allowances": {"eip155:137": true, "eip155:8453": true},
  "ready": true
}
```

When no active wallet exists, `wallet_address` and `wallet_identity_id` are `null`. Only one active EVM wallet is supported for this user-facing flow; the canonical first active identity is returned.

## Prediction Markets Enforcement

- The account-binding console obtains Core readiness server-side through `CoreAccountClient`.
- Binding session creation is blocked when Core has no active wallet.
- Completion is rejected with HTTP 409 when the submitted wallet differs from the active Core wallet.
- Address comparison is case-insensitive after EVM address validation.
- Frontend checks are convenience only; backend validation is authoritative.

## Page Design

The Polymarket page adopts the Core Account editorial layout and tokens: flat navy background, restrained green signal color, thin ledger dividers, serif display heading, square three-pixel controls, and no gradients, floating cards, or heavy shadows.

Sections:

1. Core identity: read-only Core wallet and readiness.
2. Wallet connection: Browser Wallet, OKX Wallet, or MetaMask; connect the same Core wallet.
3. Polymarket authorization: sign Clink binding and CLOB L1 auth.
4. Account controls: binding result, retry venue setup when required, and unbind Polymarket.

The page removes spending-cap creation, funding readiness, allowance approval, and spending-cap revocation. Those controls remain exclusively in Core Account.

## Error States

- Core unavailable: stop and show one next action to retry later.
- Core wallet missing: show a Core Account setup link and do not enable Polymarket authorization.
- Wrong wallet: show expected and connected shortened addresses and keep authorization disabled.
- CLOB failure: preserve the existing binding session and show one retry action.

## Verification

- Core readiness tests cover active and absent wallet addresses.
- Prediction API tests reject missing Core identity and mismatched wallets.
- Markup tests assert Core-style structure and absence of spending-cap controls.
- Existing Polymarket binding, credential storage, dashboard, and MCP tests remain green.
