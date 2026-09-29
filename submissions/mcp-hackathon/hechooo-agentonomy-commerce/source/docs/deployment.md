# Local review deployment

This deployment runs the persistent Agentonomy Commerce review service locally.
It is a reproducible review harness, not a public deployment or an attestation
of ownership or submission eligibility. Settlement is simulated and no real
funds are spent.

The service exposes two separate local entry points. The browser at `/` can use
the optional public visitor demo through `/demo/session` and `/demo/v1/*`.
Visitors click **开始演示** and receive an HttpOnly same-site cookie; they do
not enter or retrieve a review token. The private machine API remains at
`/v1/*` and continues to require the Bearer token configured in
`AGENTONOMY_API_TOKEN`.

The container listens on API port `8080`, published only to
`127.0.0.1:8080` by Compose. Open `http://localhost:8080/` so the browser
origin matches the local demo configuration. The merchant is a real HTTP
service inside the container at `http://127.0.0.1:18081/v1/reconcile`; its
port is not published to the host and it is not a configurable URL proxy. The
API uses one private worker and one persistent state directory; public visitor
workers use isolated state under that directory.

## Start with Docker

Docker and Docker Compose are required. Copy the example environment file and
replace the source commit and private review token before starting:

```bash
cp .env.example .env
# Edit .env so SOURCE_COMMIT is the exact output of `git rev-parse HEAD` and
# AGENTONOMY_API_TOKEN is a fresh token of at least 32 printable characters.
# Keep AGENTONOMY_DEMO_ORIGIN=http://localhost:8080 for the local browser demo.
# Do not commit .env.
docker compose --env-file .env up --build -d
```

`AGENTONOMY_DEMO_ORIGIN` must be the exact origin in the browser address bar.
The example enables the local demo at `http://localhost:8080`; leaving the
value empty disables `/demo/session` and `/demo/v1/*`. For an HTTPS deployment,
configure the exact HTTPS origin instead. Plain HTTP is accepted only for
localhost, `127.0.0.1`, or `::1` development.

The `SOURCE_COMMIT` build argument must be exactly the 40-character lowercase
commit that is being reviewed. Compose fails before starting if it is missing,
and the Dockerfile validates it again and bakes it into
`AGENTONOMY_SOURCE_COMMIT`. The API token is required at runtime and is never
baked into the image.

The named `review-data` volume is mounted at `/data`. The non-root process uses
UID/GID `10001:10001`; the image exposes only API port `8080`. Keep the volume
when restarting the container. `docker compose down --volumes` intentionally
deletes the review state and starts a new tenant.

## Start without Docker

Docker is optional for a local review. With the repository's existing virtual
environment, the same API can run directly on `127.0.0.1:8080`:

```bash
export AGENTONOMY_SOURCE_COMMIT="$(git rev-parse HEAD)"
export AGENTONOMY_API_TOKEN="$(.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export AGENTONOMY_DEMO_ORIGIN=http://localhost:8080
export AGENTONOMY_STATE_DIR="$PWD/.runtime/review"
export AGENTONOMY_HOST=127.0.0.1
export AGENTONOMY_PORT=8080
make PYTHON=.venv/bin/python review-api
```

Open `http://localhost:8080/` and click **开始演示**. The browser receives a
private HttpOnly visitor cookie and uses the `/demo/v1/*` aliases. Each visitor
session has its own persistent 1.00 simulated-USDC budget; a delivered report
costs 0.30. Sessions last seven days, up to 128 sessions are retained, and at
most 10 new sessions are created per rolling minute. Refreshing or replaying
never recharges or resets a session budget. All settlement remains simulated.

Keep those environment variables in the shell used for the verifier. Stop and
start the command again with the same `AGENTONOMY_STATE_DIR` to exercise a
restart without resetting state. This direct launch uses the same loopback HTTP
merchant on port `18081`; it does not create a public endpoint.

## Verify the running service

### Public browser-demo smoke check

The browser flow is the primary public-demo check: click **开始演示**, confirm
the visitor-specific budget, lock the supplied synthetic CSV quote, purchase it,
then refresh and replay the same preview or look up the same order. A second
browser profile should receive a different session and retain its own 1.00
budget. The cookie is the only browser credential; it is HttpOnly and is never
returned in JSON or page text.

For a command-line smoke check, use a local cookie jar without printing its
contents. This checks the origin gate, cookie bootstrap and isolated budget
endpoint without requiring a private review token:

```bash
DEMO_ORIGIN=http://localhost:8080
DEMO_COOKIE_JAR="$(mktemp)"
trap 'rm -f "$DEMO_COOKIE_JAR"' EXIT

curl -fsS "$DEMO_ORIGIN/demo/session"
curl -fsS -c "$DEMO_COOKIE_JAR" -b "$DEMO_COOKIE_JAR" \
  -H "Origin: $DEMO_ORIGIN" \
  -H 'Content-Type: application/json' \
  --data '{}' "$DEMO_ORIGIN/demo/session"
curl -fsS -b "$DEMO_COOKIE_JAR" "$DEMO_ORIGIN/demo/v1/budget"
curl -fsS -b "$DEMO_COOKIE_JAR" "$DEMO_ORIGIN/demo/v1/services"
```

Keep the cookie-jar file local and remove it after the check. It contains the
visitor credential even though the commands above never print it. A missing or
wrong `Origin` on a mutating demo request is rejected, and the public demo is
unavailable when `AGENTONOMY_DEMO_ORIGIN` is not configured.

The repository helper runs the same public flow, checks a second visitor's
isolation, and can resume a prior session after restart. Its private state file
is mode `0600` and contains the HttpOnly cookie credential; keep it outside the
source tree and never publish it:

```bash
.venv/bin/python scripts/verify_public_demo.py \
  --base-url http://localhost:8080 \
  --expected-commit "$(git rev-parse HEAD)" \
  --state-file /tmp/agentonomy-public-demo-state.json
```

Add `--resume` with the same private state file after restarting the service.

### Private operator API verification

The separate standard-library operator verifier checks the public health and proof documents,
rejects an unauthenticated budget request, creates one synthetic purchase,
checks the `USD 27.50` report, replays it, and confirms that budget and
settlement counters do not change on replay. It reads the bearer token from an
environment variable and writes only sanitized evidence. For Docker, set that
variable to the same token configured in `.env`; for a direct Python launch,
keep the token already generated above. Run this in another terminal with the
same token while the API is running:

```bash
: "${AGENTONOMY_API_TOKEN:?Set the token used by the running service}"
python3 -m scripts.verify_review_api \
  --base-url http://127.0.0.1:8080 \
  --expected-commit "$(git rev-parse HEAD)" \
  --evidence-file /tmp/agentonomy-review-first.json
```

The verifier prints no token, CSV input, receipt secret, wallet key, or Core
identity. Its output contains the purchase and preview IDs needed for a restart
check. After `docker compose restart review-api`, pass those IDs to avoid
creating a second preview or charge:

```bash
python3 -m scripts.verify_review_api \
  --base-url http://127.0.0.1:8080 \
  --expected-commit "$(git rev-parse HEAD)" \
  --purchase-id purchase_FROM_THE_FIRST_RESULT \
  --preview-id preview_FROM_THE_FIRST_RESULT \
  --evidence-file /tmp/agentonomy-review-after-restart.json
```

The verifier is suitable for CI. `--token-env` selects a different environment
variable name when needed; the token is never a command-line argument.

## Review limits and retention

The private review tenant starts with its existing signed simulated budget of
`1.00 USDC`; the CSV offering costs `0.30 USDC` per successful purchase. Its
initial grant expires 30 days after it is created. It is stored in persistent
Core state; restarting the container does not reset, replenish, revoke, or
recreate it. Missing or corrupt persistent metadata prevents startup. An
expired or revoked grant remains retained and causes new purchases to fail
closed; it is never silently replaced.

Each public visitor session starts in its own isolated persistent sandbox with
`1.00 USDC` simulated budget. A successful report costs `0.30 USDC`. A session
lasts seven days; at most 128 sessions are retained and at most 10 new session
identities are created per rolling minute. Reusing a valid cookie, refreshing,
or replaying an existing purchase never creates a new grant, replenishes the
budget, or resets state. There is no public reset, top-up, grant-creation, or
merchant-URL endpoint. Public demo settlement is simulated only.

The default request limit is 60 requests per minute per authenticated private
client or public visitor session. Public guest traffic is also capped at 120
requests per minute in aggregate; session bootstrap is capped at 20 requests
per minute and new identities at 10 per rolling minute. Request bodies are
limited to 256 KiB. Preview input is retained for its five-minute preview
lifetime. Durable purchase results are retained for seven days. Core, SQLite,
and public-session state remain in `/data` until the volume is deliberately
removed.

CSV input must use the columns
`transaction_id,date,description,amount,currency,category`. It is UTF-8 and
at most 128 KiB with at most 1000 data rows, including duplicate rows. Dates
are ISO dates, amounts are signed decimal values with exactly two places and an
absolute value no greater than `1,000,000,000,000`, and every row uses one
three-letter currency. Exact duplicate IDs are reported and counted once;
conflicting duplicate content is rejected. The shipped verification fixture
therefore reports two unique transactions and a net total of `27.50 USD`.

## HTTPS and public hosting

No public hostname, HTTPS reverse proxy, certificate, or user-domain
configuration is supplied by this repository. A deployment owner must provide
those values and terminate HTTPS before exposing the API outside the local
host. Set `AGENTONOMY_DEMO_ORIGIN` to that exact HTTPS origin; the visitor
cookie is marked Secure for HTTPS. The public health and proof responses
identify the configured source commit and project slug, but they are not
deployment or rights evidence. No public deployment or completed browser
verification is claimed by this local documentation.
