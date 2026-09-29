# Agent Spending Mandate Implementation Plan

## Goal

Make Clink Core the single wallet identity and bounded spending control plane used by Marketplace and Prediction Markets. Users configure one signed mandate in the Core Account console; compatible purchases execute without per-purchase prompts while every reservation remains policy checked and audited.

## Product Contract

- Core owns wallet identity, spending mandate, rolling budgets, allowance verification, pause/revoke, policy references, and audit history.
- Marketplace owns service discovery, quote locking, delivery, and payment-rail negotiation.
- Prediction Markets owns venue credentials and order execution, but reads the same Core mandate.
- Automatic payment is allowed only when the selected rail can be executed by Core from an active verified allowance. External EIP-3009 x402 remains a per-purchase signature fallback.

## Core Changes

1. Extend spending grants with `hourly_limit_usdc`, `merchant_trust_scopes`, and `notification_mode`.
2. Add a rolling usage ledger keyed by finalized/reserved reservation timestamps and enforce the one-hour limit atomically during reservation.
3. Return total, hourly, and daily remaining budget from authorization resolution.
4. Include the new terms in signed grant challenges. Existing grants remain readable but are not treated as auto-pay mandates until explicit values exist.
5. Allow unsigned updates only when every changed term is equally or more restrictive. Expanded limits, expiry, networks, assets, products, venues, merchants, or trust scope require a new signed grant challenge.
6. Add account-console controls for per-transaction, one-hour, one-day, total, expiry, networks/assets, merchant trust, notification mode, pause, and revoke.
7. Record notification disposition in account/funding audit metadata; silent mode suppresses user interruption, not auditing.

## Marketplace Changes

1. Add payment capability metadata to quote comparison and preview responses.
2. Report `auto_pay_compatible=true` only for Core-settled allowance rails with an active mandate and verified allowance.
3. Remove the unconditional registry-verified confirmation gate when the grant trust scope explicitly permits registry-verified merchants and Core policy approves.
4. Prefer `clink_payer_proxy` for compatible external x402 purchases; return a concise compatibility reason and checkout URL only for the `external_x402_signature` fallback.
5. Preserve idempotent reserve/settle/finalize behavior and never retry a paid-but-undelivered purchase by charging again.

## Prediction Markets Changes

1. Surface Core mandate limits, remaining hourly/daily/total budgets, notification mode, and account URL in readiness.
2. Keep Polymarket CLOB authorization separate from Core wallet ownership.
3. Reuse Core authorization resolution for funding and order-related spend checks.

## Verification

- Unit tests for grant validation, restrictive updates, signed expansions, and rolling-hour enforcement.
- Reservation concurrency/idempotency tests for hourly and daily budgets.
- Marketplace tests for capability negotiation, silent in-limit auto-pay, and external x402 fallback.
- Prediction readiness tests for shared mandate projection.
- Run focused test suites in all three repositories, then full suites where runtime permits.
