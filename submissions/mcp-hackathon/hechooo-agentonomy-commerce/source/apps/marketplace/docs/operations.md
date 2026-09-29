# Clink Marketplace Operations

Clink Marketplace is deployed as its own stack. Clink Core is deployed separately and must be reachable only over a private network. Do not publish Core, PostgreSQL, or Redis directly to the internet.

## Environment

Create the runtime file once and keep it outside version control:

```bash
cp .env.example .env
chmod 600 .env
```

At minimum, replace:

- `POSTGRES_ADMIN_PASSWORD`, `POSTGRES_MIGRATION_PASSWORD`, `POSTGRES_API_PASSWORD`, and `POSTGRES_WORKER_PASSWORD` with four distinct passwords of at least 16 characters. The bootstrap admin credential is not injected into application roles.
- `MARKETPLACE_INTERNAL_API_TOKEN` with the internal token used by the MCP process when it calls protected Marketplace API routes.
- `CLINK_CORE_INTERNAL_API_TOKEN` with the same internal token configured in Clink Core.
- `CLINK_CORE_*_SERVICE_URL` with private Core service addresses reachable from the containers. Do not use `127.0.0.1` for Core when Core is outside this Compose project.
- Merchant/admin, SIWE, peer Registry, EIP-3009, and public URL settings for the target environment.
- `MARKETPLACE_NATIVE_PROVIDER_IDS` with the comma-separated canonical provider IDs approved for Clink allowance, or leave it empty to fail closed to external x402.

Compatible external x402 services can use Core's Universal Payer without any
Marketplace-side private key. Core must advertise all of the following from its
authenticated funding readiness endpoint before Marketplace selects that rail:

- `universal_payer_ready=true` and `automatic_payment_rail=clink_payer_proxy`;
- identical `payer_address` and `spender_address` values;
- an exact `supported_assets[network]` match for the selected payment asset.

Fund the Core relayer with native gas on every enabled network and keep enough
USDC allowance available from the user wallet for the signed mandate. If readiness
is incompatible, Marketplace creates a per-purchase signing preview instead. If a
live merchant challenge later proves incompatible, the current proxy purchase
releases its reservation and fails before payer funding; create a new explicit
external x402 signing preview rather than mutating or replaying it. Marketplace
never receives the Core relayer private key.

Both internal API tokens must be at least 32 characters and must not use the
placeholder values from `.env.example`. Set one of these administrator modes:

```dotenv
# Enable administration for explicit EVM wallets.
MARKETPLACE_ADMIN_DISABLED=false
MARKETPLACE_ADMIN_WALLETS=0xabc...,0xdef...

# Or explicitly disable all administrator operations.
MARKETPLACE_ADMIN_DISABLED=true
MARKETPLACE_ADMIN_WALLETS=
```

Compose uses `.env` only as its interpolation source. It does not inject the
complete file into any service. Each role receives an explicit allowlist:

| Role | Injected configuration |
| --- | --- |
| `postgres` | Bootstrap admin plus migration/API/worker role bootstrap passwords |
| `migrate` | Migration-owner PostgreSQL connection fields only |
| `marketplace-api` | Restricted API database role, Redis, Core URLs/token, MCP-to-API token, trusted native allowlist, merchant/admin and Registry settings |
| `marketplace-worker` | Restricted worker database role, Redis, Registry/verification/worker settings, trusted native allowlist and Core URLs/token |
| `marketplace-mcp` | Marketplace API host/port, MCP listener and MCP-to-API token only |

The MCP container never receives the database password, Core token, or admin
wallets. The worker never receives the MCP-to-API token or admin configuration.
Migration never receives business tokens. Compose also forces production
validation and container-local dependency addresses:

```text
MARKETPLACE_DEPLOYMENT_MODE=production
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/1
```

The PostgreSQL init script creates a migration role that owns the database/schema
and separate API/worker roles with DML and sequence grants but no DDL ownership or
schema `CREATE`. The container entrypoint constructs `MARKETPLACE_DATABASE_URL` with SQLAlchemy's
URL builder. The raw database password is never interpolated into
`docker-compose.yml`. API, worker, and MCP refuse to start in production when a
required token is empty, weak, or a known placeholder. Migration performs only
the database preflight and does not require business tokens.

Compose environment files have their own `$` interpolation rules. Put passwords,
tokens, and other secrets containing `$`, spaces, `@`, or `:` in single quotes so
they are passed literally:

```dotenv
POSTGRES_ADMIN_PASSWORD='admin: cash$money with space'
POSTGRES_MIGRATION_PASSWORD='migrate: cash$money with space'
POSTGRES_API_PASSWORD='api: cash$money with space'
POSTGRES_WORKER_PASSWORD='worker: cash$money with space'
```

Do not use double quotes for a secret containing `$` unless you intentionally
apply Compose escaping. `docker compose config` may display a literal dollar as
`$$` in its canonical output; the container receives one `$`.

The runtime image uses allowlisted source directories only. The build context
also excludes `.env`, PEM/private-key formats, credential JSON, secret
directories, local databases, logs, and runtime JSONL files. Never bake secrets
into the image or commit `.env`.

## Start Or Upgrade

Run the same commands for a first deployment and an upgrade:

```bash
git pull origin dev
docker compose --env-file .env build
docker compose --env-file .env config
docker compose --env-file .env up -d
```

For a non-default environment filename, pass it as Compose's interpolation
source:

```bash
docker compose --env-file .env.production config
docker compose --env-file .env.production up -d
```

The `migrate` service runs `alembic upgrade head`. API, worker, and MCP wait for PostgreSQL and Redis health plus a successful migration before starting. All business roles reuse the same immutable image.

On a fresh PostgreSQL volume, role bootstrap runs automatically before migration.
For an existing volume created before role separation, bootstrap the three roles
once with the existing database owner before switching runtime services to this
Compose file; then verify the database/schema owner is
`clink_marketplace_migrate` and API/worker lack schema `CREATE`.

To run only the migration during a controlled release:

```bash
docker compose --env-file .env run --rm migrate
```

Before an upgrade, record the current image tag and database revision, then take
a PostgreSQL backup using the platform backup mechanism. `alembic upgrade head`
is the supported production migration direction. Do not run a production
downgrade merely to roll back application code.

Recommended release sequence:

```bash
git pull origin dev
docker compose --env-file .env config
docker compose --env-file .env build
docker compose --env-file .env run --rm migrate
docker compose --env-file .env up -d --no-deps marketplace-api marketplace-worker marketplace-mcp
docker compose --env-file .env ps
curl --fail http://127.0.0.1:8050/livez
curl --include http://127.0.0.1:8050/healthz
.venv/bin/python scripts/public_mcp_surface_smoke.py --live
```

If the new application image is unhealthy, restore the previous immutable image
tag and restart the three business roles while retaining the migrated database.
Use database restore only when a migration itself is proven incompatible and a
tested restore procedure is available.

## Exposure

- Marketplace API: `127.0.0.1:8050`
- Marketplace MCP: `127.0.0.1:9050/mcp/`
- PostgreSQL and Redis: internal Compose network only; no host ports
- Clink Core: separate deployment, private network only

Terminate public TLS at a reverse proxy and publish only the exact API/MCP routes needed by the product. Keep merchant/admin endpoints behind the intended authentication and network policy.

## Operator Consoles

The API image serves two framework-free consoles from allowlisted `web/` assets:

- `/merchant` connects a browser EVM wallet, performs SIWE, searches and claims Bazaar candidates, edits/submits Manifest JSON, signs `ManifestClaim`, verifies the domain and live x402 response, reads owned status, and disables offerings.
- `/admin` performs SIWE with an allowlisted wallet, reads Registry/worker/Core/metric status and provider summaries, triggers Registry sync, and suspends or restores providers.

The browser never receives database credentials, Redis configuration, the Core internal token, or the MCP-to-API token. It never accepts wallet secret material. The SIWE bearer is stored only in `sessionStorage`, so closing the tab clears browser-side authentication. Reverse proxies must serve the consoles and `/assets/*` from the same origin as the API so bearer requests remain same-origin. Configure `MARKETPLACE_SIWE_ALLOWED_DOMAINS` with the exact browser domain used by that origin.

All merchant list/status routes resolve ownership from the merchant session. All new admin read routes call the same admin session/allowlist guard as suspend, restore, and Registry sync. Do not replace those checks with proxy-only authentication.

## Health And Status

Container liveness is intentionally independent from Core availability:

```bash
curl --fail http://127.0.0.1:8050/livez
docker compose --env-file .env ps
```

Operational readiness includes worker, Registry freshness, and Core connectivity and can return HTTP 503 while the API remains alive:

```bash
curl --include http://127.0.0.1:8050/healthz
curl --head http://127.0.0.1:9050/mcp/
```

`/healthz` is intentionally a lightweight readiness contract. It returns only the
API, worker, Registry, and Core readiness projection; it does not compute or return
the operator analytics fields `metrics` or `supply_targets`. After SIWE
authentication with an allowlisted administrator wallet, use `GET /admin/status`
for the full operational payload, including both analytics fields.

Use `/livez` for the API container healthcheck. Use `/healthz` for alerts and release readiness, not automatic restart decisions.

When `MARKETPLACE_ADMIN_DISABLED=true`, every `/admin` route returns HTTP 403,
including the admin console and requests from wallets still present in the
allowlist. Set it to `false` only when the configured allowlist should be active.

## Logs

```bash
docker compose --env-file .env logs -f marketplace-api
docker compose --env-file .env logs -f marketplace-worker
docker compose --env-file .env logs -f marketplace-mcp
docker compose --env-file .env logs migrate
```

Worker stage failures are isolated and reported by `/healthz`. Existing verified catalog data remains queryable while external Registry or Core dependencies are degraded.

The Bazaar inventory is larger than one worker-cycle page budget. A fresh
`running` Registry status means the durable cursor is progressing and is healthy;
it is not a partial failure. The authenticated `/admin/status` response returns
`supply_targets` for the ten default pilot targets. Each item remains `discovered`
until its real merchant claims and locally verifies it, so a non-zero candidate
count with zero verified offerings is expected during supplier onboarding.

Targeted discovery intentionally searches Bazaar without the catalog network or
price filter, then records whether a result is first-party, branded, or merely
powered by the named service. Buyer-side network and price constraints still
apply to search, quote, preview, and execution. Override the default target list
only with valid JSON in `MARKETPLACE_BAZAAR_TARGETS_JSON`; leave it empty to use
the documented CoinGecko/Nansen/Allium/Firecrawl/Exa/Alchemy/Pinata/Venice/
ElevenLabs/dTelecom set.

## Stop And Recovery

Graceful stop keeps the PostgreSQL data volume. Redis purchase input is intentionally
memory-only: persistence is disabled and `/data` is tmpfs, so a Redis restart drops it
and the purchase fails safely before payment rather than recovering plaintext:

```bash
docker compose --env-file .env down
```

Do not add `--volumes` in production unless the database has been backed up and deletion is intentional. Runtime processes use `exec`, receive `SIGTERM`, and have a 30-second grace period.

After correcting configuration or dependency failures:

```bash
docker compose --env-file .env up -d
docker compose --env-file .env ps
curl --include http://127.0.0.1:8050/healthz
```

## Container Smoke

The smoke test ignores any externally supplied `COMPOSE_PROJECT_NAME`, creates an
unpredictable `clink-marketplace-smoke-*` project, chooses free loopback ports,
and uses a temporary environment file. Cleanup refuses to remove volumes unless
the project name matches the strict smoke prefix. It never replaces the
operator's `.env` or touches a production Compose project:

```bash
bash scripts/container_smoke.sh
```

It verifies image build, a non-root runtime user, readable merchant/admin web assets,
migration exit code, separated database role ownership/grants, memory-only Redis,
API liveness, MCP listener, and the dedicated worker process.
It also places a temporary secret sentinel in the build context and verifies the
allowlisted runtime image did not copy it. Parallel jobs can pin ports when
needed with `MARKETPLACE_SMOKE_API_PORT` and `MARKETPLACE_SMOKE_MCP_PORT`.

## Deterministic Business Smoke

The Bazaar pilot smoke is entirely local. It uses SQLite, an in-memory ephemeral
store, a paginated Bazaar fixture, a fake Core gateway, a fake merchant endpoint,
and deterministic EVM signatures. It never accesses a real Registry, wallet,
merchant, token, or payment rail:

```bash
.venv/bin/python scripts/bazaar_pilot_smoke.py
```

The smoke proves that an unverified candidate is not public, then follows the
merchant claim and verification boundaries before quote, preview and purchase.
It also proves transient result handling and idempotent replay.

The MCP contract smoke is offline by default and requires no running services:

```bash
.venv/bin/python scripts/public_mcp_surface_smoke.py
```

After deployment, run the live transport mode:

```bash
.venv/bin/python scripts/public_mcp_surface_smoke.py --live
```

A `503 degraded` response from the health tool is a readiness result, not an MCP
transport failure. Investigate its worker, Registry and Core fields before
releasing traffic.

## Release Verification

Run before tagging or deploying:

```bash
.venv/bin/pytest -q
.venv/bin/python scripts/bazaar_pilot_smoke.py
.venv/bin/python scripts/public_mcp_surface_smoke.py
.venv/bin/python -m compileall adapters services shared storage mcp_servers scripts
bash -n run_demo.sh run_demo_stop.sh run_demo_status.sh scripts/*.sh
.venv/bin/alembic heads
docker compose --env-file .env config
git diff --check
```

`bash scripts/container_smoke.sh` is the dynamic image/runtime check and requires
a running Docker daemon. When Docker is unavailable, record that check as an
environmental residual risk; do not repeatedly wait or treat static Compose
validation as a substitute for the dynamic container smoke.
