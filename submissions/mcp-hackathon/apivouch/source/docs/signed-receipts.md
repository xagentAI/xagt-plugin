# Signed Receipts

## Configuration

Signing configuration is read once at process startup from the environment, not from files, requests, or the database. Restart after rotation. No private material is returned by discovery, receipt APIs, configuration repr, or configuration errors.

| Variable | Contract |
| --- | --- |
| `REQUIRE_SIGNED_RECEIPTS` | Defaults to literal `false`. Only exact lowercase `true` and `false` are valid; whitespace, empty strings, `1`, and other spellings are configuration errors. |
| `RECEIPT_SIGNING_PRIVATE_KEY_B64` | Optional canonical standard base64 of exactly 32 raw Ed25519 private-key bytes (44 characters including padding). PEM, whitespace, URL-safe/noncanonical encodings, and other lengths are rejected. Supply through the deployment secret environment, never commit a key. An explicitly empty value is invalid. |
| `RECEIPT_SIGNING_KEY_ID` | Optional override matching `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Otherwise `ed25519-` plus the first 32 lowercase SHA-256 hex characters of the raw public key. An override without a private key is invalid. |

Without a key and with the default requirement, issuance preserves unsigned v1 receipts byte-for-byte in structure: no added authenticity field. With a valid key, all new receipts use signed v2, including UNVERIFIED refusals. Any invalid signing configuration fails issuance closed, even when signing is optional. A missing required key also fails closed. These configuration checks run before provider calls and prevent receipt storage. REST (including demos) and legacy MCP issuance return HTTP 503 with `{"detail":"Receipt signing unavailable"}`; modern MCP returns HTTP 200 with a complete tool result, `isError: true`, and the safe message `Tool execution unavailable`.

Runtime signing happens after provider evaluation, so providers may already have been called when signing fails. These failures also fail closed: no unsigned fallback, returned receipt, or stored receipt. The transport-specific errors are the same as for configuration failures.

Signing configuration errors do not raise during application import: `/health` remains available. `GET /ready` checks deployment configuration, bounded database connectivity, and `app.core.signing.SIGNING_CONFIG.ready`. If signing configuration is not ready, it returns HTTP 503 with `checks.signing: false`. Readiness checks configuration, not a runtime signing operation. `load_signing_config()` loads a fresh configuration for isolated tests; production uses the startup singleton.

## Wire Contract

The v2 format supports [independent deployment verification](deployment-verifier.md). Omit top-level `receipt_id` and `integrity`; serialize sorted keys, compact separators, unescaped Unicode, UTF-8, and reject nonfinite numbers. SHA-256 yields the lowercase fingerprint hex, with `sha256:` prefix in `integrity.fingerprint`; the first 24 hex characters form `receipt_id`.

The hashed payload contains exactly `authenticity: {"state":"signed","algorithm":"Ed25519","key_id":"KEY_ID"}`. `integrity.signature` is standard base64 of the 64-byte Ed25519 signature over UTF-8 `apivouch-outcome-receipt-v2\n` followed by the 64 fingerprint hex characters, without the `sha256:` prefix or a trailing newline. The entire integrity object, including the signature, is outside the hash.

`GET /.well-known/apivouch-signing-key.json` returns exactly `schemaVersion: 1`, `slug: "apivouch"`, `algorithm: "Ed25519"`, `keyId`, `publicKey` (standard base64 raw32), and `commit` (the configured deployment commit). Unconfigured optional signing returns 404; invalid configuration returns safe 503. No private-key representation is exposed.

## Offline Verification

```bash
python examples/verify_outcome_receipt.py receipt.json public-key.json
```

Use the discovery document as `public-key.json`. V2 verification requires the pinned production `cryptography` dependency. Output separately reports `integrity_valid` and `authenticity: {state, valid}`. Exit 0 requires valid integrity and either unsigned v1 or valid signed v2; signed receipts without a supplied key document fail with authenticity unavailable. V1 needs no key or crypto import. The existing `verify(receipt)` function remains integrity-only for legacy consumers.

REST and MCP retrieval also report integrity separately from authenticity and never rewrite stored receipts. Legacy unsigned v1 remains verifiable after signing is required. The server verifies signed receipts against its current key; retain old public discovery documents externally for offline verification after rotation. This is a single active key implementation, not a historical key registry.

Hash integrity alone does not establish authenticity: an attacker can edit content and recompute a hash. Signatures prevent that forgery relative to a trusted public key. Same-origin discovery proves consistency with that deployment, not externally pinned operator identity, and does not independently attest upstream HTTP observations. Pin or authenticate the public document through a trusted channel for issuer identity. Deployment commit validation remains the independent deployment verifier's responsibility.
