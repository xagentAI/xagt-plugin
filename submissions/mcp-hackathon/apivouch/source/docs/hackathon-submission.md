# APIVouch — X-Agent MCP Hackathon submission draft

## Track

General Challenge (Open Innovation).

APIVouch is agent reliability infrastructure, not an on-chain security or
auditing product. Its callable task is to resolve one API-backed outcome from
independent providers while enforcing schema, origin, price, latency, and
agreement constraints.

## One-line capability

APIVouch routes an agent goal across independent public APIs, rejects invalid
or disagreeing evidence, and returns one constraint-bound outcome with a stored,
tamper-evident receipt that the agent can re-verify through MCP.

## Why an agent uses it

An agent cannot safely act on the first API response when a provider may be
down, over budget, schema-invalid, redirected to the same origin, or disagreeing
with independent sources. APIVouch turns those uncertainties into a deterministic
`VERIFIED` or `UNVERIFIED` result and preserves the decision evidence.

## Verifiable call

```bash
python scripts/verify_hackathon.py --live
```

This initializes the MCP server, lists the public tools, calls three independent
public exchange-rate providers, stores the resulting receipt, re-verifies its
SHA-256 integrity through MCP, and checks that the health and deployment-proof
endpoints report the same source commit.

For a network-independent reviewer check:

```bash
python scripts/verify_hackathon.py
```

Judges can also open the public Receipt Explorer at `/receipts/<24-hex-receipt-id>` from any demo **View public proof →** link, and run the **Chaos & Refusal Lab** section (**Run all safety scenarios**) for six deterministic in-process safety proofs. Lab execution accepts no request body, repeats with identical canonical receipt JSON and signatures from a fixed fixture timestamp, stores fixtures in an isolated table that can never evict production evidence, and proves canonical JSON round-trip exactly equal on retrieval. Scenario PASS is distinct from receipt VERIFIED/UNVERIFIED; a correct UNVERIFIED refusal is a green PASS. Deterministic fixtures are not live-provider evidence.

## MCP surface

- `apivouch_resolve_verified_outcome`: call 2–5 independent providers and issue
  a constraint-bound evidence receipt.
- `apivouch_verify_receipt`: retrieve a stored receipt and recompute its
  integrity fingerprint.

Streamable HTTP / JSON-RPC endpoint: `POST /mcp`.

## Safety and data declaration

- Caller-supplied providers must use distinct HTTP(S) network origins.
- Redirects are checked again for origin independence.
- Private, loopback, link-local, and cloud-metadata targets are blocked by
  default.
- Query-string values are redacted from receipts; full request URLs are stored
  only as SHA-256 digests.
- Response bodies are represented by digests and bounded scalar previews.
- No customer API credentials are stored.
- Price is a transparent quote; this release does not move payment.
- The deterministic fixture is explicitly labelled and separate from the live
  public-provider demonstration.

## Monetization

Free calls can verify public, zero-cost providers. A paid hosted tier can charge
per verified outcome rather than per attempted provider call, with higher plans
for longer receipt retention, private provider connectors, organization policy,
SLA monitoring, and managed evidence retention. Signed v2 exports are already
implemented. The current release reports quoted
provider costs but deliberately performs no settlement.

## Deployment values

- Public deployment URL: `https://apivouch.sklab.cc`
- Health URL: `https://apivouch.sklab.cc/health`
- Deployment proof: `https://apivouch.sklab.cc/.well-known/xagent-verification.json`
- Exact 40-character deployed commit: returned by both endpoints above and
  checked by `scripts/verify_deployment.py`
- Public source repository: `https://github.com/ShahadatTest/apivouch`

The deployment gate requires `/health` and the deployment proof to return the
same expected commit before release evidence is accepted.

## Evidence Boundary

The primary story is one verified outcome or honest refusal. SHA-256 integrity
is not authenticity; v2 Ed25519 authenticates relative to a trusted key.
Same-origin discovery does not independently identify an operator or attest
upstream calls. The public explorer states this limitation explicitly. No payment or settlement is implemented; quoted prices are labelled not charged / no settlement.

`verify_hackathon.py` uses local TestClient, not a deployment. Use the independent
`verify_deployment.py` with explicit HTTPS origin, exact expected SHA, and
deterministic mode as the required deployment gate. Live mode is separate;
exit 2 is unavailable, not success. Fixtures/mocks are not live evidence. Modern
MCP is a locally tested JSON subset, not official conformance. The HTTPS VPS
deployment is public; its reviewed release SHA is accepted only when the independent
gate matches both health and proof responses. Backup restore and official validator
evidence are not claimed here.
