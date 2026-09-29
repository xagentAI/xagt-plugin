# Reviewer demo

## One-click path

Public URL: `https://apivouch.sklab.cc`. This is a runbook, not an executed
transcript; verify the reviewed commit through `/health` and the deployment proof
before each review. Start with the deterministic failure fixture, then treat
real-provider calls separately. Mocked tests and fixtures do not prove live availability.

1. Open the deployed root page.
2. Choose **Call real providers** and confirm that at least two of Frankfurter, Floatrates, and ExchangeRate-API agree on the USD→EUR reference rate.
3. Confirm `provider_independence.required` through the API receipt; all three URLs use distinct public origins and redirect convergence is checked.
4. Choose **Run failure fixture**. Confirm that Atlas and Beacon agree, Legacy is rejected for returning a string instead of a number, and Offline Express is rejected for HTTP 503.
5. Confirm the selected provider, quoted call price, agreement threshold, review commit, and receipt fingerprint.
6. Follow the visible **View public proof →** link to `/receipts/<receipt_id>` and confirm the Receipt Explorer shows the same VERIFIED verdict, separate integrity and authenticity states, and a not charged / no settlement price label.
7. In **Chaos & Refusal Lab**, choose **Run all safety scenarios** and confirm 6/6 safety scenarios behaved as expected. Open one refusal proof link and confirm UNVERIFIED displays as a green scenario PASS. These deterministic fixtures are not live-provider evidence.
8. Confirm `integrity_verified_after_storage` is `true`; this is a second read-and-hash check, not a UI-only claim. Then choose **Run self-contained live demo** in the provider lab.
9. APIVouch imports its deliberately incomplete Shop API contract and makes three bounded calls to each safe operation.
10. Inspect the response-shape drift, generated contract, MCP tool schemas, and project MCP URL.
11. Open **Exhaustiveness proof**: the demo has already traversed three catalog pages and certified exactly seven records.
12. Try `MAX`, field `price`, candidate `p2`, then export the evidence pack.

The expected local reference result is approximately 54/100 for the source and 82/100 for the generated contract. Scores can change when scoring rules or the deliberately inconsistent demo contract change; the response itself is authoritative.

## Manual API path

The product-level MCP tools are available at `POST /mcp`. Its `tools/list`
result contains `apivouch_resolve_verified_outcome` and
`apivouch_verify_receipt`.

```bash
curl http://localhost:8000/demo/openapi.json
```

Post that object as `openapi_json` to `POST /api/projects`, then call:

```text
POST /api/projects/{id}/test       {"samples_per_endpoint":3}
POST /api/projects/{id}/contract   {}
POST /api/projects/{id}/prove      {"operation_id":"listItems","claim_type":"EXACT_COUNT","expected_count":7,"arguments":{"limit":3}}
POST /mcp/{id}                     {"jsonrpc":"2.0","id":1,"method":"tools/list"}
GET  /api/projects/{id}/export
```

## Negative evidence

The outcome demo intentionally proves that APIVouch refuses insufficient evidence. A provider cannot join the consensus group after an HTTP failure, schema failure, cost violation, latency violation, outlier result, or duplicate network origin. If the requested agreement count is not reached, APIVouch returns `UNVERIFIED`, selects no provider, and quotes zero selected cost.

The Chaos & Refusal Lab makes the same refusal logic judge-visible without live calls: `consensus-success` proves selection, while `provider-disagreement`, `schema-invalid`, `upstream-failure`, `over-budget` (zero provider calls), and `origin-convergence` (final-origin rejection) each prove an honest UNVERIFIED refusal. `POST /api/outcomes/lab/{scenario_id}` accepts no request body; each run uses a fixed fixture timestamp and latency, stores its receipt in an isolated lab table that can never evict production evidence, and proves canonical JSON round-trip exactly equal on retrieval. Scenario PASS is distinct from receipt VERIFIED: PASS means the safety behavior matched expectation. Same-origin signature discovery proves consistency with this deployment, not independent truth of upstream data. No payment is executed.

The provider-lab demo proves that APIVouch does not hide upstream variability. Different successful JSON shapes become `OBSERVED_SHAPE_DRIFT`; the generated schema represents the observed union and the MCP runtime provides a stable outer result envelope.

It also demonstrates positive proof under a stable `demo-catalog-v1` snapshot. The collector receives page sizes only; all returned items, cursors, totals, and snapshot evidence come from the demo API itself.

## Independent Gate

Run `scripts/verify_deployment.py` with explicit `--base-url`, exact
`--expected-commit`, and `--mode deterministic`; optionally follow with
`--mode live`. Exit 2 means live UNVERIFIED, not success. See [verifier](deployment-verifier.md).
The UI integrity indicator proves neither issuer identity nor upstream truth.
Signed v2 adds authenticity relative to a trusted key. Prices are quotes, with
no payment. See [modern MCP](mcp-modern.md) for direct calls and tested limits.
