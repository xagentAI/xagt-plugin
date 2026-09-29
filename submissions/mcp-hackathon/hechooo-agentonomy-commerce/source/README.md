# Agentonomy Commerce

让 Agent 在用户授权预算内，可靠地购买服务并取得结果。

Agentonomy Commerce contains the Clink runtime for service discovery, spending
mandates, policy checks, budget reservations, payment verification and delivery.
Agents use one `clink_node` MCP entry. The Core controls funds; Marketplace
manages the purchase and returns the result.

## Run locally

Use Python 3.12 for the reproducible environment below.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e apps/node
make PYTHON=.venv/bin/python test-commerce
make PYTHON=.venv/bin/python demo
```

The local demonstration uses simulated external settlement. It does not spend
real funds, contact production services or require a wallet key/API key. Core
budget accounting and Marketplace purchase transitions use the shipped business
implementation. See [architecture](docs/architecture.md) for the code boundary.

See [demo instructions and MCP client setup](docs/demo.md) for the full flow,
expected evidence and simulated boundaries.

## Persistent review service

The review API provides a **real HTTP CSV reconciliation merchant** over the
same Core authorization and Marketplace purchase logic. Settlement is explicitly
simulated: each report costs 0.30 simulated USDC from a 1.00 simulated USDC
budget. No real funds are spent.

Follow [deployment instructions](docs/deployment.md) to launch the service
locally or build its container. When `AGENTONOMY_DEMO_ORIGIN` is set to the
exact browser origin, opening `/` and clicking **开始演示** creates or restores
an HttpOnly `agentonomy_demo` visitor session. The browser uses
`/demo/session` and `/demo/v1/*`; visitors do not enter or retrieve a review
token. Each visitor has an isolated persistent 1.00 simulated USDC budget,
with 0.30 charged per delivered report. A session lasts seven days; at most
128 sessions are retained and at most 10 new sessions are created per rolling
minute. Refreshing the page or replaying a purchase reuses the same persisted
session and never recharges or resets its budget.

The private machine API remains separate: `/v1/` capabilities still require
the private Bearer review token, and its original persistent review tenant,
budget and order state are not shared with public visitor sessions. The local
public demo is disabled unless its exact origin is configured; for Compose or
the direct local launch, use `http://localhost:8080`.

State persists across restarts. Replaying a purchase preserves its settlement
and result instead of charging again. Reports are retained for seven days;
the private tenant's signed bootstrap grant expires after 30 days and is never
automatically replaced. These are simulated sessions and simulated settlement,
not a multiuser production wallet service.

```sh
make PYTHON=.venv/bin/python test-review test-submission
```

The original stdio MCP demo above is independent and ephemeral. It does not
share the private review tenant, public visitor sessions or CSV service. The
full shipped `clink_node` runtime remains the Agent entry for Core and
Marketplace.

## Hackathon submission

The official submission is [PR #83](https://github.com/xagentAI/xagt-plugin/pull/83).
Its package contains an exact committed source snapshot, SHA-256 manifest,
rights declaration and deployment evidence. The public review site is
[review.agentonomy.xyz](https://review.agentonomy.xyz).

[Submission preparation](submission/README.md) documents the packaging format.
`scripts/package_submission.py --output DIR` deliberately creates a draft;
publication requires fresh deployment and validation evidence for the selected
commit. A submission PR is not an acceptance decision.

See the [two-minute review walkthrough](docs/review-walkthrough.md) for the
demo sequence and the exact boundaries of each claim.

## Existing runtime

The original Node protocol and module names are retained. The full source for
Core, Marketplace, Node, Hosted Facilitator and the USDC executor is included.
Prediction Markets remains as an optional compatibility module and is disabled
for Commerce's local demonstration.

```sh
make PYTHON=.venv/bin/python test-workspace test-node test-e2e
make PYTHON=.venv/bin/python test-apps test-hosted
make test-contracts
```

The existing Personal and Server runtime configuration examples are
`clink.node.example.toml` and `clink.node.server.example.toml`. Connecting real
wallets, RPC endpoints or Hosted signing infrastructure is a separate deployment
step; the local demo does not certify that configuration.

## Source and rights

This is a focused export of the Clink working tree. It has independent Git
history and contains no Clink runtime databases, credentials or private deployment
state. Export hashes are in [source-manifest.json](docs/source-manifest.json).
Original in-file license notices are retained. No additional repository-wide
open-source license has been granted by this export.
