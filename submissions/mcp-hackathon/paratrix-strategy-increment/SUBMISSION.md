# Strategy Increment

- **Team:** [karpak-labs](https://github.com/karpak-labs)
- **Capability:** simulated strategy research and reproducible analysis
- **Source:** [karpak-labs/strategy-increment](https://github.com/karpak-labs/strategy-increment)
- **Workbench:** [Strategy Increment](https://strategy-increment.raspy-boat-dbb0.workers.dev/)
- **API:** [OpenAPI schema](https://strategy-increment.raspy-boat-dbb0.workers.dev/openapi.json) · [Interactive documentation](https://strategy-increment.raspy-boat-dbb0.workers.dev/docs)
- **License:** [MIT](LICENSE)
- **Support:** [GitHub Issues](https://github.com/karpak-labs/strategy-increment/issues)

## Problem and value

A candidate strategy's standalone performance does not establish its contribution to an existing strategy. Researchers need to know whether the combined drawdown improves, how much return is sacrificed, and whether the apparent improvement simply comes from reducing exposure to the baseline.

Strategy Increment compares baseline A, an initial 80% A + 20% B allocation, and an initial 80% A + 20% cash allocation over the same interval. The cash control measures the effect of reducing baseline exposure. Four research criteria make the return/drawdown tradeoffs explicit, and a complete evidence package lets collaborators independently reproduce the calculation.

## Deliverables

| Capability | Task a user or agent can complete |
| --- | --- |
| Simulated equity import | Create A/B snapshots from JSON or built-in examples |
| Comparability checks | Identify incompatible dates, valuation clocks, currencies, costs, or completeness |
| Three-scenario experiment | Calculate three equity paths, returns, and drawdowns over a fixed interval |
| Criteria evaluation | Inspect each actual difference, predefined threshold, and outcome |
| Experiment history | Read saved experiments and create derived experiments while preserving the original |
| Evidence export | Download original structured inputs, normalized curves, rules, provenance, versions, and results |
| Offline reproduction | Verify an exported package using the same calculation engine |

The delivery includes the complete Python implementation, a Chinese-language research workbench, an HTTP API/OpenAPI schema with English descriptions and messages, pinned dependencies, Cloudflare Workers build and storage configuration, five examples, behavior tests, and verification materials. The full workflow uses simulated results and requires no live trading account or order permissions.

## Review path

1. Open the [workbench](https://strategy-increment.raspy-boat-dbb0.workers.dev/) and choose an example, or start a local instance using the [run instructions](source/README.md).
2. Run a facts-only comparison and inspect the three scenarios and four differences.
3. Set all four criteria and examine passing and failing conditions. Use the missing-day example to check input rejection.
4. Change the interval or criteria and confirm that a derived record is created while the original remains available.
5. Download the evidence package and reproduce it offline using the [verification steps](verification/README.md).

| Endpoint | Capability |
| --- | --- |
| `GET /health` | Service health and build version |
| `POST /v1/data-snapshots` | Create an input snapshot |
| `POST /v1/comparison-inputs/validate` | Check whether two inputs are comparable |
| `POST /v1/experiments` | Create a three-scenario experiment |
| `GET /v1/experiments/{id}/evidence` | Export reproducible evidence |
| `GET /.well-known/xagent-verification.json` | Report deployment version binding |

The [health endpoint](https://strategy-increment.raspy-boat-dbb0.workers.dev/health) and [deployment proof](https://strategy-increment.raspy-boat-dbb0.workers.dev/.well-known/xagent-verification.json) report the deployed source commit. The review package includes a generated `submission.json` containing that release's source revision and service addresses. Package generation and validation are described in the [release guide](source/docs/RELEASE.md). Requests, expected successes, and safe error responses are documented in [verification/README.md](verification/README.md).

## Invocation and reproduction

Research endpoints use an anonymous signed-cookie session and require no API key. Agents and CLI clients must preserve one cookie jar across snapshot creation, experiment execution, and evidence retrieval. Session isolation does not establish a registered user identity. See the [implementation contract](source/docs/IMPLEMENTATION-CONTRACT.md); the service exposes `/openapi.json` and interactive documentation at `/docs`.

To run the Worker locally, install Python 3.13 or 3.14, Node.js 22 or later, and uv 0.12.3 or later. Run from `source/`:

```bash
python3 scripts/build_worker.py
cd runtime/worker-bundle
npm ci
uv run --locked pywrangler dev --local
```

Open the local workbench at `http://127.0.0.1:8787`. Behavior tests and offline reproduction commands are documented in [validation](source/docs/VALIDATION.md). Local development and deployment use the same Worker entrypoint and Durable Object storage. To apply source changes, stop Wrangler, rebuild, and restart; the [development workflow](source/docs/DEPLOYMENT.md#edit-and-rerun) preserves local sessions and updates code and assets together.

Cloudflare Workers build, HTTPS, version binding, persistent storage, and operational controls are documented in the [deployment guide](source/docs/DEPLOYMENT.md). Examples and JSON imports need no external credentials. Session quotas limit stored records. Account-wide request-rate controls and resource budgets are operator-managed settings.

## Method and scope

The model fixes initial allocations, performs no portfolio rebalancing, and assumes zero cash return. It requires complete daily UTC simulated equity curves. Criteria use percentage points and are evaluated before display rounding. Historical results describe changes relative to the baseline and cash control; they do not predict future returns. See [METHOD.md](source/docs/METHOD.md) for the full definitions.

The Worker supports JSON imports and built-in simulated examples. External Nexus imports are disabled; see [source adapters](source/app/adapters/README.md).

## Data handling and provenance

Signed-cookie sessions isolate inputs and experiments. Cloudflare Workers persists records in session-scoped SQLite-backed Durable Objects. Only the owning session can export its evidence. Limits are 2 MiB per request, 5,000 daily points per curve, 100 snapshots per session, and 100 experiments per session. Runtime data, credentials, and installed dependency directories are excluded from the source package.

Cookies last 30 days. Expiring or deleting a cookie does not delete stored records. Records support experiment reproduction and are retained and cleaned by the operator according to the [deployment guide](source/docs/DEPLOYMENT.md); there is no automatic expiry-deletion task.

Examples and imported JSON are processed by this service. The Worker makes no external Nexus calls. Workbench assets are served by this application. Interactive documentation at `/docs` loads Swagger UI from jsDelivr and an icon from the FastAPI documentation site. `/openapi.json` can be read directly.

First-party licensing, dependencies, and AIMM sample provenance are documented in [RIGHTS.md](RIGHTS.md). Recorded verification scope is documented in [VALIDATION.md](source/docs/VALIDATION.md).

## Release identity

Review commit: `040c70f5ca044a8c38610952b4ba174b559474ba`

The deployment health and proof endpoints must report this exact source revision.
