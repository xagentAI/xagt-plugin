# Clink Universal Payer Design

## Goal

Allow one Core wallet mandate to authorize bounded Agent spending across compatible Marketplace merchants without requiring a fresh user signature for every purchase.

The user still signs once per chain and asset to establish an on-chain allowance. Each merchant payment remains a fresh x402 authorization, but Clink signs that authorization from a controlled payer account after Core has atomically approved and reserved the user's mandate.

## Product Boundary

- Core owns wallet identity, mandates, rolling limits, policy, risk, allowance verification, reservations, payer signing, settlement reconciliation, and audit.
- Marketplace owns discovery, quote locking, merchant challenge validation, delivery, and purchase state.
- Hermes chooses services and requests purchases through Marketplace only. It never receives payer keys or calls Core directly.
- Prediction Markets may reuse the mandate for funding, but Polymarket CLOB order authorization remains venue-specific.

## Payment Rails

1. `clink_allowance`: a Clink-native merchant accepts a Core receipt after Core transfers funds under the user's allowance.
2. `clink_payer_proxy`: a compatible external x402 merchant receives a standard merchant-scoped payment signed by the Clink Universal Payer.
3. `external_x402_signature`: the user signs the merchant-scoped payment when the proxy rail is unavailable or policy requires it.

## Proxy Purchase Flow

```text
Marketplace locks quote and obtains merchant 402 challenge
-> Core validates mandate, policy context, destination and challenge
-> Core atomically reserves user budget
-> Core validates the canonical token domain and signs one short-lived merchant-scoped EIP-3009 payment
-> Core pulls the exact amount from the user allowance into the payer treasury
-> Marketplace submits the payment to the merchant
-> Core verifies merchant PAYMENT-RESPONSE and on-chain settlement
-> Marketplace records delivered or paid_but_undelivered
-> Core finalizes reservation and audit references exactly once
```

## Security Invariants

- The payer private key is runtime-only and never returned through APIs, MCP, logs, receipts, or Marketplace storage.
- The merchant challenge must match the locked quote: scheme, network, asset, amount, payTo, resource, and expiry.
- A proxy reservation binds user, grant, allowance, purchase, merchant, destination, amount, network, asset, payer, challenge hash, nonce, and validity window.
- Reservation, reimbursement, payer authorization, merchant submission, and finalization are idempotent.
- A retry may reuse a funded reservation, but must never pull the user amount twice.
- Once merchant settlement is proven, the purchase can only become `delivered` or `paid_but_undelivered`; it cannot be charged again automatically.
- Proxy auto-pay is allowed only for supported EVM x402 exact/EIP-3009 challenges and trust tiers explicitly allowed by the mandate.
- Unsupported networks, assets, challenge formats, high-risk decisions, unavailable payer liquidity, and out-of-limit purchases fail closed to `external_x402_signature` or manual confirmation.

## Treasury Model

The first production implementation uses the existing native facilitator relayer address as the Universal Payer. It must hold enough USDC working capital and gas on each enabled network. Core creates a valid merchant payment authorization before the reimbursement side effect, but Marketplace cannot submit it until the user reimbursement has been confirmed. This prevents malformed or unsupported merchant challenges from debiting the user.

This creates two independently reconciled legs:

1. user wallet -> Clink payer treasury through the verified allowance;
2. Clink payer treasury -> merchant through standard x402 settlement.

Core records both transaction hashes. A purchase is not complete until both legs reconcile.

## Compatibility

Compatibility is negotiated per quote. `clink_payer_proxy` requires:

- x402 v2 exact payment;
- an enabled EVM network and canonical USDC asset;
- an EIP-3009 payment requirement that Core can reproduce exactly;
- a verified merchant destination and a non-expired quote;
- a Core mandate and chain allowance that cover the purchase;
- a healthy payer with sufficient balance and gas.

No claim is made that every arbitrary merchant is automatically compatible. The Marketplace exposes the selected rail and fallback reason for each quote.
