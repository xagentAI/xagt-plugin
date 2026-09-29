# SafeGate Commerce Outcome

## Capability

- **One-line description:** Verifies whether a Base Mainnet USDC payment is bound to a valid SafeGate-signed completed-commerce attestation and returns a deterministic commerce outcome.
- **Who it helps:** AI agents, merchant systems, and commerce infrastructure that need post-payment verification and evidence.
- **Capability boundary:** Read-only verification. It does not custody funds, initiate payments, sign transactions, approve tokens, perform fulfillment, or expose the private SafeGate core.

## Live API

- **API base URL:** https://safegate-xagent-commerce-outcome.vercel.app/v1
- **SafeGate website:** https://safegatelabs.xyz
- **Commerce demo surface:** https://www.safeshelf.store
- **Health-check URL:** https://safegate-xagent-commerce-outcome.vercel.app/health
- **Authentication:** none
- **Rate limits / known limits:** No application-level custom rate limit. Hosting-platform and Base Mainnet RPC limits may apply. Base RPC timeout is 12 seconds.
- **API contract:** POST /v1/commerce-outcome with a SafeGate commerce attestation. GET on the same endpoint returns capability metadata.

## Source and reproducibility

- **Source repository:** https://github.com/Nurexen-Labs/safegate-xagent-commerce-outcome
- **Review commit:** b460b88ce800839e69839a5d31aac949dfe2543c
- **Source submitted in this PR:** source/
- **Run syntax checks:** cd source && npm run check
- **Run tests:** cd source && npm test
- **Run locally:** From source/, set XAGENT_REVIEW_COMMIT=b460b88ce800839e69839a5d31aac949dfe2543c and run vercel dev.
- **Deploy:** Deploy source/ to Vercel with XAGENT_REVIEW_COMMIT set to the exact review commit.
- **Version binding:** /health and /.well-known/xagent-verification.json both expose the exact review commit.

## Verification

- **Health-check result:** HTTP 200, status=ok, commit=b460b88ce800839e69839a5d31aac949dfe2543c.
- **Capability call:** POST /v1/commerce-outcome with a SafeGate-signed review attestation.
- **Expected success:** COMMERCE_VERIFIED with PAYMENT_VERIFIED, VALID attestation, FULFILLMENT_COMPLETED, and EVIDENCE_CREATED.
- **Expected error behavior:** Invalid or tampered attestations return HTTP 400 verification errors. Base RPC timeout or upstream RPC failures return HTTP 502.
- Repeatable evidence is documented in verification/README.md.

## Security and data handling

- **Data collected:** Submitted commerce-attestation fields and transaction identifiers required for verification.
- **Purpose and retention:** Request data is processed for verification. The submitted application source implements no persistent request-payload storage.
- **Third parties / outbound network calls:** Base Mainnet JSON-RPC via https://mainnet.base.org by default, or operator-supplied BASE_RPC_URL.
- **Secrets:** No secrets or private signing keys are committed. The Ed25519 public verification key is intentionally included.
- **Known risks / restrictions:** Payment is independently checked on Base Mainnet. Fulfillment and evidence status are trusted only when carried by a valid SafeGate Ed25519 attestation. Availability partly depends on the Base RPC endpoint.

## Support

- **Team / builder:** Nurexen Labs
- **Submitter:** Rahmi Özal
- **X:** @NurexenLabs
- **LinkedIn:** Rahmi Özal
- **License / rights:** See RIGHTS.md. No additional open-source license is granted by this submission.
