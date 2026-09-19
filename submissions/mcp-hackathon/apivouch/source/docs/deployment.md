# Deployment and Operations

These are operator instructions, not evidence of a deployment. Public URL and
reviewed release commit remain **pending**. The primary capability is a verified
outcome or honest refusal, not an API directory. No payment is executed.

## Ubuntu VPS First Deploy

Use a supported Ubuntu LTS host with sufficient disk for images, PostgreSQL,
backups, and logs (start with 2 GiB RAM; builds may need more). Install security
updates, Git, Python 3 with venv, OpenSSL, and Docker Engine plus the Compose v2
plugin from Docker's official Ubuntu repository. Verify `docker version` and
`docker compose version`. Docker-group membership is effectively root access.
Use a non-root SSH operator with keys, disable password/root SSH only after
testing a second session, and enable unattended security updates.

Create DNS A (and AAAA only if IPv6 actually works) for the desired hostname.
Allow inbound TCP 80/443 and SSH only from operator addresses in the provider
firewall; deny everything else for IPv4 and IPv6. Mirror policy in UFW, but do
not rely on UFW alone: Docker-published ports can bypass its normal rules.
Never publish 8000 or 5432. Check externally that they are unreachable.

Clone the source, fetch and check out the exact reviewed 40-hex commit in a clean
release checkout. Run commands below from that repository root. Do not label a
dirty build with an older commit. Verify `git status --porcelain` is empty and
`git rev-parse HEAD` equals the independently reviewed SHA before building.

```bash
export GIT_COMMIT="$(git rev-parse HEAD)"
export PUBLIC_BASE_URL=https://apivouch.example.com
export ACME_EMAIL=operator@example.com
```

Replace the example origin/contact. The origin must be HTTPS with no path, query,
credentials, or trailing slash. Application readiness validates the exact SHA
and origin; Compose additionally fails on missing required values. Compose uses
`deploy/vps/docker-compose.yml`, not the root local-only Compose file.

## Secrets

Disable shell tracing (`set +x`) and use `umask 077`. For first initialization,
generate secrets directly into the operator process environment, without printing
them or writing key files in the checkout:

```bash
set +x
umask 077
export POSTGRES_PASSWORD="$(openssl rand -hex 32)"
export RECEIPT_SIGNING_PRIVATE_KEY_B64="$(openssl rand -base64 32)"
```

The latter is a random raw 32-byte Ed25519 seed in canonical standard base64,
not PEM. Preserve both values using an approved encrypted secret manager before
ending the session; use its environment injection for subsequent operations.
Do not regenerate on every upgrade. The application reads the key only from its
startup environment. Do not pass it as a CLI argument, Docker build argument,
GitHub repository variable, source file, or workflow secret. Never run `env`,
`docker inspect`, shell tracing, or rendered `docker compose config` in shared
logs: those can disclose secrets. Docker administrators can read container
environments; this is not protection from host compromise. The tracked
`.env.example` files are documentation only. No real `.env` is required.

```bash
docker compose -f deploy/vps/docker-compose.yml config --quiet
docker compose -f deploy/vps/docker-compose.yml build --pull app
docker compose -f deploy/vps/docker-compose.yml up -d --wait
docker compose -f deploy/vps/docker-compose.yml ps
```

Caddy obtains/renews public TLS certificates using ports 80/443 and persists its
state. DNS propagation, ACME reachability, and issuance must succeed before public
verification. The app runs UID 10001, read-only with bounded tmpfs, concurrency,
and logs. Only Caddy publishes host ports. Caddy and app share an outbound-capable
edge network; app and PostgreSQL share a separate internal database network.
The app retains internet access for public providers while SSRF policy remains
`ALLOW_PRIVATE_NETWORK=false`. PostgreSQL and Caddy state use named volumes.
Do not run `down -v`, volume prune, or remove these volumes during upgrades.

Caddy caps incoming bodies at 1 MB, header/body reads at 10/30 seconds, writes
at 120 seconds, and upstream response headers at 110 seconds. App imports cap
at 512 KiB and outbound responses at 1 MiB. Long project/proof jobs may exceed
the proxy timeout; this is not a guarantee of completion for every bounded job.
The public API is not authenticated or tenant-isolated. Limit exposure and
monitor abuse/storage; add edge rate limiting/access controls for a real service.
Restart policies restart exited processes, not merely unhealthy containers.

## Required Release Gate

Install pinned production dependencies in an operator venv, then run:

```bash
python scripts/verify_deployment.py --base-url "$PUBLIC_BASE_URL" --expected-commit "$GIT_COMMIT" --mode deterministic --require-signed
python scripts/verify_deployment.py --base-url "$PUBLIC_BASE_URL" --expected-commit "$GIT_COMMIT" --mode live --require-signed
```

Deterministic is mandatory: health/proof/readiness, MCP, rejection fixtures,
stored receipts, independent hashes and signatures when v2 is issued. Inspect
that production reports include `receipt.signature`; the general verifier also
supports unsigned local deployments. Live is a separate provider-availability
check: exit 2 means a valid UNVERIFIED outcome, not success; exit 1 is a broken
invariant/transport. Do not turn either into a passing deployment claim.
Archive the public key discovery document through a trusted channel and pin it
for issuer authentication; discovery alone only proves same-origin consistency.
Readiness checks connectivity/configuration/signing, not schema completeness.
Check stored receipt retrieval after restart as a persistence acceptance test.

## Upgrade and Rollback

Record the current exact image tag, source SHA, public key document, and secret
manager version. Take and test a DB backup first. Fetch the reviewed new SHA in
a clean release checkout; retain the old image, same Compose project name,
volume names, origin, and secrets. Export the new exact `GIT_COMMIT`, build app,
then `up -d --wait` and run both gates. This single-host procedure has downtime;
it is not zero-downtime deployment. Review dependency image updates and schema
changes explicitly; never auto-upgrade the PostgreSQL major version on a volume.

For code-only rollback with compatible schema, restore the old release checkout
and `GIT_COMMIT`, then `docker compose -f deploy/vps/docker-compose.yml up -d
--no-build --wait`. Retain/inject the same signing and database secrets. Verify
against the old SHA, not the failed upgrade SHA. If schema is incompatible,
stop app/Caddy and restore the matching pre-upgrade DB backup before restarting
the old image. Restoring a backup discards writes since that backup; obtain
operator approval and preserve a separate current backup first. No migration
framework or automatic schema rollback is provided.

## PostgreSQL Backup and Restore

Use an encrypted, access-controlled directory outside the repository, e.g.
`/var/backups/apivouch`, owned by the operator with mode 0700. In a shell with
the existing secrets and release configuration injected:

```bash
umask 077
backup=/var/backups/apivouch/$(date -u +%Y%m%dT%H%M%SZ).dump
docker compose -f deploy/vps/docker-compose.yml exec -T db pg_dump -U apivouch -d apivouch -Fc > "$backup"
test -s "$backup"
docker compose -f deploy/vps/docker-compose.yml exec -T db pg_restore --list < "$backup"
```

Check every exit status, encrypt/copy backups off-host, retain according to an
explicit policy, and alert on failures/disk capacity. Listing is not a restore
test: regularly restore into an isolated PostgreSQL 17 instance and exercise
receipt retrieval. Backups contain user evidence and must not become CI artifacts.
Also preserve secrets in the secret manager; the DB does not contain signing keys.

Destructive restore into the existing service (maintenance window, approved
backup, pre-restore backup already secured):

```bash
docker compose -f deploy/vps/docker-compose.yml stop caddy app
docker compose -f deploy/vps/docker-compose.yml exec -T db dropdb -U apivouch --if-exists apivouch
docker compose -f deploy/vps/docker-compose.yml exec -T db createdb -U apivouch -O apivouch apivouch
docker compose -f deploy/vps/docker-compose.yml exec -T db pg_restore -U apivouch -d apivouch --no-owner --exit-on-error < "$backup"
docker compose -f deploy/vps/docker-compose.yml up -d --wait
```

Stop on errors; do not reopen traffic after a partial restore. Re-run readiness,
the deterministic gate, and retrieval of a known pre-backup receipt. PostgreSQL
password environment changes only initialize an empty volume; rotating a DB
password requires a coordinated database-role password change and app restart.

## Signing Rotation

Single active key only: no historical server key registry. Archive the old public
document and receipts before rotation, securely retain the old private key only
as required by rollback policy, generate a new seed, update the secret manager,
and recreate app. Default key IDs derive from the public key; never reuse an
override ID for a different key. Old signed receipts remain unchanged and hash
verifiable, but server authenticity verification may become unavailable with
the new key. Verify them offline with their archived, trusted public document.
Do not rotate mid-review without coordinating reviewer pins and rollback plans.
On compromise, revoke trust out of band; no revocation registry is implemented.

## Scheduled Verification

Set repository variables `APIVOUCH_DEPLOYMENT_URL` (exact HTTPS origin, no trailing
slash) and `APIVOUCH_EXPECTED_COMMIT` (deployed lowercase 40-hex SHA). The
`deployment-verification` workflow runs daily and manually. Missing configuration
fails, never skips to green. The required deterministic step has a 240-second
process bound, the job a 10-minute bound; sanitized JSON artifacts expire after
7 days. Manual `live=true` adds a live check only after deterministic success;
exit 2 stays non-success. No private signing key is available to this workflow.
Configure alerts and inspect failed runs; scheduling alone is not an uptime SLA.

## Render Alternative

`render.yaml` remains supported with the root non-root multi-stage Dockerfile
and private PostgreSQL. Set `PUBLIC_BASE_URL`, `REQUIRE_SIGNED_RECEIPTS=true`, and
the private `_B64` key in Render's secret environment. Keep private-network
access disabled. Render provides `RENDER_GIT_COMMIT` when `GIT_COMMIT` is unset;
verify it against the independently reviewed commit. Configure readiness at
`/ready`, backups, and edge body/time/rate limits using platform capabilities;
the VPS Caddyfile does not apply to Render. Check current plan availability,
database retention, sleep behavior, and pricing instead of assuming free plans
are durable production hosting. Run the same deployment gates. Neither path has
been deployed merely by adding these files.
