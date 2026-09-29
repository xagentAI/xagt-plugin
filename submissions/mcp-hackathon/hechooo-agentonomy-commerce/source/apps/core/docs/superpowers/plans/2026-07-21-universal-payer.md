# Clink Universal Payer Implementation Plan

## Goal

Extend the existing unified spending mandate so Marketplace can automatically pay compatible external Bazaar x402 merchants within signed limits, while preserving exact-once debit, merchant delivery safety, and venue-specific Prediction Markets authorization.

## Core

1. Add `clink_payer_proxy` to reservation schemas and persist proxy payment provenance.
2. Validate proxy reservations against an active mandate, verified asset allowance, payer identity, merchant destination, and canonical challenge hash.
3. Add a proxy prepare operation that validates and signs a merchant-scoped EIP-3009 payload before any reimbursement, then idempotently reimburses the payer once before submission.
4. Add a proxy finalize operation that verifies the merchant payment response and both on-chain legs before issuing the Core receipt.
5. Expose payer readiness by network without revealing secrets.
6. Add tests for tampering, replay, duplicate prepare/finalize, insufficient allowance, insufficient treasury, quote drift, expired authorization, and paid-but-undelivered recovery.

## Marketplace

1. Negotiate `clink_payer_proxy` for compatible registry-verified external x402 offers when the Core mandate allows their trust tier.
2. Keep `external_x402_signature` as a fail-closed fallback with an explicit reason.
3. During execution, lock the merchant 402 challenge, reserve through Core, request the payer payload, submit it, and finalize through Core.
4. Do not expose a checkout URL for a successfully selected proxy rail.
5. Preserve the current external checkout path for unsupported quotes and manual-policy cases.
6. Add tests proving in-limit purchases do not request a user signature and retries do not produce a second debit.

## Prediction Markets

1. Document that the shared mandate can fund supported venue accounts through Core.
2. Keep Polymarket CLOB order signatures and account authorization separate from generic Marketplace payments.
3. Surface Universal Payer readiness only where it affects funding; do not imply that it authorizes venue orders.

## Verification

- Run focused Core reservation and Universal Payer tests.
- Run focused Marketplace commerce, external x402, and proxy execution tests.
- Run complete test suites in Core and Marketplace.
- Run Prediction Markets readiness and execution tests.
- Review API responses and logs for key material, signatures, checkout tokens, and internal bearer tokens.
