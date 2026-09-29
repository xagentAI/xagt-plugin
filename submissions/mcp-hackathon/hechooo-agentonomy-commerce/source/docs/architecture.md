# Architecture and source boundary

Agentonomy Commerce is an independent export of the Clink working tree, focused
on reliable service procurement. The internal `clink_node` name and existing
Core contracts are retained so that authorization and financial rules are not
rewritten during migration.

Agent → unified Node MCP → Marketplace → Core → payment execution/verification.
Marketplace requests authorization and settlement from Core, then requests and
returns the service result. Core owns identity, signed grants, policy/risk,
reservation accounting and audit. Marketplace cannot grant itself a budget.

`apps/core`, `apps/marketplace`, `apps/node`, `apps/facilitator` and `contracts`
contain the complete first-party implementation. `apps/prediction-markets` is
retained for compatibility with existing Node imports and regression contracts;
it is not the Commerce demo's product focus. Generic Linux installer code is
retained. Private production deployment assets, user-specific acceptance
fixtures, databases, credentials and Git history are excluded.

`docs/source-manifest.json` records hashes at export time; subsequent Commerce
changes are tracked by this repository's Git history. It is provenance for the
export, not a claim that every later file still has its initial hash.

The demo is a local rehearsal, not evidence of a live blockchain transaction.
External chain/risk/service fixtures must be explicit and isolated from the
production implementation. Production wallet keys are never part of this repo.

## Authorization handoff correction

Commerce corrects one imported Marketplace integration gap: after Core resolves
an active signed grant, `PurchaseService.execute` now passes Core's explicit
`user_interaction_required` decision as the policy request's
`requires_confirmation`. Only the boolean `false` permits silent purchase;
missing or invalid values continue to require confirmation. It does not invent
`user_confirmed=true`, bypass risk decisions or replace Funding's fresh
signature, mandate, allowance and budget checks.

The local MCP test demonstrates a signed `silent_under_limits` grant purchasing
without per-purchase confirmation. Six focused regression cases cover the
handoff, including fail-closed handling of unknown values.

## Persistent HTTP review composition

`agentonomy_commerce.api` serves isolated public visitor sessions alongside a
private operator review tenant. Each browser receives an HttpOnly cookie after
clicking Start demo; only its credential hash is persisted. Public `/demo/v1`
requests select the server-owned sandbox path for that session; private `/v1`
requests retain Bearer authentication and separate state. Mutating public calls
require an exact configured Origin. A single additional guest worker is closed
before switching visitors and reopens the original persisted budget and orders.
Sessions expire after seven days; refresh never replaces a valid grant.

The bounded subprocess bridge runs the Marketplace
composition separately from Core, preserving their existing module namespaces.
There is no API for selecting a wallet, changing a price, granting more budget,
resetting an order, or choosing an arbitrary merchant URL.

Browser / API client → authenticated API → Marketplace worker → persistent Core
worker → simulated RPC settlement → real loopback HTTP merchant → CSV report.

The bootstrap signs one 1.00 sandbox USDC grant for 30 days. The wallet signing
key is used in memory for setup and is not persisted. Core's SQLite identity,
grant, reservations and audit, a protected receipt HMAC secret, public bootstrap
metadata and a simulated transaction journal survive process restarts. A
single-owner lock prevents concurrent Core instances. Incomplete or corrupt
state fails startup; expiry and revocation never trigger a replacement grant.

Marketplace freezes the CSV input and 0.30 price in a five-minute preview.
`Idempotency-Key` binds repeated preview requests to the same input. An existing
preview/purchase is replayed through the production state machine, preserving
settlement identity. A seven-day SQLite result mailbox and the merchant's own
idempotency ledger preserve delivery evidence across restarts. Expired merchant
results leave tombstones, so replay cannot compute a new delivery under the
same expired order. Reads purge expired payloads; metadata and audit remain.

The catalog keeps a fixed logical HTTPS identity,
`https://merchant.agentonomy.invalid/v1/reconcile`, to retain the imported
public-endpoint model constraints. A dedicated transport maps **only this
fixed resource** to `http://127.0.0.1:<merchant-port>/v1/reconcile` using a real
HTTP socket. The `.invalid` address is not a public deployment. The merchant
checks the Core-signed purchase scope, receipt signature, settled state, price,
network and payee. It resolves the signed purchase ID to Marketplace's stored
input hash before accepting the CSV body. The Agent cannot choose this mapping.

All public capability responses disclose `real_funds: false`,
`settlement_mode: simulated` and `service_transport: http`. The health/proof
commit is a deployment configuration claim; independent source/build/endpoint
checks are required before treating it as public deployment evidence. The
container smoke check binds it to the build commit and exercises purchase and
replay across a container restart.
