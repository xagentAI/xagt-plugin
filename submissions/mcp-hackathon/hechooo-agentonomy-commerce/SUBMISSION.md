# Agentonomy Commerce

> Submission: Agentonomy supplied its identity and support contact and authorized publication of the nonsensitive code and materials after personal sample identifiers were replaced. Public HTTPS browser, visitor-isolation, purchase/replay and restart verification passed for the exact review commit below; see the attached evidence.

## Capability

- **One-line description:** Let an Agent purchase a service within a user-authorized budget and reliably retrieve its result; the review demonstrates paid CSV reconciliation.
- **Who it helps:** Agents operating a user-authorized commerce budget.
- **Capability boundary:** Core and Marketplace validate identity, policy, budget, payment evidence, and merchant delivery. Merchant computation uses real HTTP to a loopback listener through the signed logical resource `https://merchant.agentonomy.invalid/v1/reconcile`. Settlement is simulated, `real_funds` remains false, and no real funds are spent.

The public browser demo uses synthetic CSV input and simulated USDC only. It is a review sandbox, not a production wallet, a live-chain payment, or a formal security audit.

## Public browser review

- **Review URL:** [https://review.agentonomy.xyz](https://review.agentonomy.xyz)
- **Entry flow:** Open the URL, click **开始演示**, lock the supplied CSV quote, and confirm the purchase. No signup, token entry, or organizer credential is required.
- **Public routes:** `GET /demo/session` checks the current browser session; explicit `POST /demo/session` creates or restores it. The capability aliases are `/demo/v1/services`, `/demo/v1/budget`, `/demo/v1/previews`, `/demo/v1/purchases`, and `/demo/v1/purchases/{purchase_id}`.
- **Browser credential:** The server sets an `HttpOnly`, `SameSite=Strict` cookie scoped to the browser. HTTPS deployments mark it `Secure`; it is never returned in page text or JSON.
- **Isolation and retention:** Each browser session has an isolated persistent sandbox with a 1.00 simulated-USDC starting budget. A delivered report costs 0.30 simulated USDC. Sessions last seven days; at most 128 sessions are retained and at most 10 new sessions are created per rolling minute. Refreshing, restoring the cookie, and replaying an existing purchase reuse the same session and do not charge, reset the budget, or create a new grant.
- **Traffic and CSRF limits:** Each visitor is limited to 60 requests per minute and public guest traffic is capped at 120 requests per minute globally. Mutating demo calls require an `Origin` exactly equal to the configured public demo origin.

The private `/v1/*` API remains Bearer-authenticated for operators and automation. Its original persistent review tenant, budget, order state, and verifier path are isolated from public visitor sessions and remain available as the private baseline. Public review does not require access to that operator credential.

`GET /health` and `GET /.well-known/xagent-verification.json` are public version-binding endpoints. Before review, both must identify the exact application commit below.

## Source and reproducibility

- **Source repository:** https://github.com/HEchooo/agentonomy-commerce
- **Review commit:** `029cd0ba9aff3c25fffa33ae27f94615c1eebe2b`
- **Complete review source:** `source/`
- **Run tests:** `make PYTHON=.venv/bin/python test-commerce test-review test-submission`
- **Run locally:** `make PYTHON=.venv/bin/python demo` (simulated settlement only)
- **Deploy:** See [deployment instructions](source/docs/deployment.md). Configure the exact HTTPS origin in `AGENTONOMY_DEMO_ORIGIN` before exposing the browser demo.
- **Version binding:** The health and proof endpoints must expose this exact commit before any deployment result is treated as evidence.

The local and public review flows keep the merchant transport and settlement semantics explicit: the merchant request is real HTTP to a loopback service, while settlement and all USDC accounting are simulated. No production wallet, private key, customer data, or live-chain transaction is part of this submission.

## Source integrity and historical metadata

The authoritative snapshot is the outer `source-manifest.json` together with `source-manifest.sha256`, bound to the review commit above. `source/docs/source-manifest.json` is inherited historical Clink working-tree metadata; it is preserved in the source export but does not describe or validate this review snapshot. Use the outer manifest for submission validation and do not infer current file coverage from the inherited file.

## Verification

The primary review is the public browser flow described in `verification/README.md`. That document also describes the standard-library helper `source/scripts/verify_public_demo.py`, which uses a private `--state-file` outside the source tree and `--resume` to restore the same cookie-backed session after a restart without issuing a new charge. The helper requires no credentials and never prints the cookie credential.

The current evidence artifacts are `verification/public-demo-evidence.json`, `verification/upgrade-evidence.json`, and `verification/TEST_RESULTS.md`. They are the records to inspect for the exact deployment, browser, restart, and test status for this commit; the current artifacts record successful public deployment and browser/restart verification.

The API verifier sample should show two unique transactions, duplicate ID `t1` (the browser sample uses `demo-001`), and a USD net total of `27.50` from the supplied synthetic CSV. A replay should return the same result and leave the visitor budget at 0.30 used, 0.70 remaining, one settlement submission, and one merchant delivery. A second browser session must have its own 1.00 budget and must not read the first session’s order or preview.

## Security and data handling

- **Data collected:** Bounded synthetic CSV input, public-session authorization state, purchase state, and redacted result metadata.
- **Purpose and retention:** Preview/input records expire after five minutes; delivered results and visitor sessions expire after seven days; expired visitor state is removed during subsequent session creation. Session credentials are hashed in the server ledger; they are delivered only as HttpOnly cookies and never logged or exposed in page text or JSON.
- **Third parties / outbound network calls:** The merchant is an internal logical `.invalid` resource routed to a fixed loopback HTTP listener. Core and Marketplace run in the local composition; review tests do not call production services.
- **Secrets:** No credentials, private keys, wallet material, or runtime deployment configuration are committed. Public browser review needs no credential handoff from the organizer.
- **Known limits:** Public visitor budgets and request limits are deliberately bounded. Settlement is simulated and is not evidence of a live blockchain transaction. This submission makes no formal security-audit or real-funds claim.

## Support

- **Team / builder:** Agentonomy
- **Contact:** fengjie@alvinsclub.ai
- **License / rights:** See [RIGHTS.md](RIGHTS.md); the declaration applies to this sanitized submission. Third-party terms remain applicable and no blanket relicensing is asserted.
