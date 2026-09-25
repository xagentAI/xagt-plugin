# Run and deploy

Strategy Increment runs on Cloudflare Python Workers, with session data in SQLite-backed Durable Objects and the workbench served through a Workers Assets binding. Local development uses Wrangler to run the same Worker entrypoint, FastAPI application, asset binding and Durable Object storage.

The public origin is `https://strategy-increment.raspy-boat-dbb0.workers.dev`. Its [health endpoint](https://strategy-increment.raspy-boat-dbb0.workers.dev/health) and [deployment proof](https://strategy-increment.raspy-boat-dbb0.workers.dev/.well-known/xagent-verification.json) identify the deployed source revision.

## Local Worker

Prerequisites: Python 3.13 or 3.14, Node.js 22 or later, and `uv` 0.12.3 or later. The Worker runtime and tools are pinned under `workers/`. The root `pyproject.toml` and `uv.lock` define the Python test and verification environment.

Run from `source/`:

```sh
python3 scripts/build_worker.py
cd runtime/worker-bundle
npm ci
uv run --locked pywrangler dev --local
```

Open `http://127.0.0.1:8787`. The generated bundle contains the Python application, exact recorded fixture bytes, and pinned toolchain manifests. It is excluded from Git and submission packages. The builder generates an owner-readable `.dev.vars` file with a random session secret. Rebuilding preserves that secret and `.wrangler` local storage, so existing local sessions continue to work.

The default origin is `http://127.0.0.1:8787`. When using another port or origin, rebuild with `--public-origin` matching that address and start Wrangler on the corresponding port.

## Cloudflare resources and configuration

| Setting | Purpose |
| --- | --- |
| Worker name | `strategy-increment`; must match the connected Cloudflare Worker |
| `SESSIONS` binding | SQLite Durable Objects using the exported `SessionStore` class |
| `ASSETS` binding | Workbench HTML, JavaScript and CSS; requests pass through the application first |
| `SESSION_SECRET` | Runtime secret of at least 32 random characters; signs session cookies |
| `PUBLIC_ORIGIN` | Actual public HTTPS origin, without a path; supplied to the release build |
| `COOKIE_SECURE` | Set to `true` by the release build |
| Review commit | Actual Git HEAD embedded by the release build; never entered as an arbitrary version label |

The `v1` migration creates the SQLite-backed class. No separate D1 database, R2 bucket, or filesystem volume is needed. Transactions serialize quota checks, overlap classification and record insertion within each session. Large records are split into UTF-8-safe chunks; history queries read summaries instead of loading all result payloads.

The Worker supports public examples and simulated equity JSON imports. Its external Nexus connection is disabled.

## Connect the GitHub repository

An account administrator can authorize the Cloudflare GitHub integration for `karpak-labs/strategy-increment`. Repository access and runtime secrets are configured in Cloudflare; no access token belongs in this repository.

Configure the Worker's encrypted runtime secret `SESSION_SECRET`, then connect the Git repository under **Settings → Build**. Obtain the Worker's public origin before enabling repository builds.

Use these build settings:

| Setting | Value |
| --- | --- |
| Repository | `karpak-labs/strategy-increment` |
| Production branch | The reviewed release branch, normally `main` |
| Root directory | `source` |
| Build variable `PYTHON_VERSION` | `3.13.14` |
| Build variable `NODE_VERSION` | `22` |
| Build variable `SKIP_DEPENDENCY_INSTALL` | `1` |
| Build variable `PUBLIC_ORIGIN` | `https://strategy-increment.raspy-boat-dbb0.workers.dev` |
| Preview builds | Disabled; the public proof is tied to a production origin and commit |

Build command:

```sh
python3 -m venv runtime/cloudflare-tools && runtime/cloudflare-tools/bin/python -m pip install uv==0.12.19 && python3 scripts/build_worker.py --release && cd runtime/worker-bundle && npm ci
```

Deploy command:

```sh
PATH="$PWD/runtime/cloudflare-tools/bin:$PATH" sh -c 'cd runtime/worker-bundle && uv run --locked pywrangler deploy'
```

The release builder requires a clean Git checkout and a valid HTTPS `PUBLIC_ORIGIN`. It embeds the exact source commit and a digest of the application, assets, dependency locks and build configuration. Build-generated files live under the ignored `runtime/` directory. The runtime secret must be added to the Worker's encrypted variables, not merely to build variables. Do not rotate it on each build: rotation invalidates existing session cookies.

These settings follow Cloudflare's [Git integration](https://developers.cloudflare.com/workers/ci-cd/builds/), [build configuration](https://developers.cloudflare.com/workers/ci-cd/builds/configuration/), [build image](https://developers.cloudflare.com/workers/ci-cd/builds/build-image/), and [Python deployment](https://developers.cloudflare.com/workers/languages/python/) interfaces. Validate hosted execution with representative and maximum-size inputs against the account's resource limits.

## Deploy from an authorized workstation

From a clean release checkout, run in `source/`:

```sh
export PUBLIC_ORIGIN=https://strategy-increment.raspy-boat-dbb0.workers.dev
python3 scripts/build_worker.py --release --public-origin "$PUBLIC_ORIGIN"
cd runtime/worker-bundle
npm ci
uv run --locked pywrangler deploy
```

Authenticate using Cloudflare's supported login or an appropriately scoped deployment identity. Set the encrypted `SESSION_SECRET` for this named Worker before accepting traffic. Keep credentials outside Git and command output.

After deployment, run the [API verification flow](../../verification/README.md). Confirm that `/health`, `/.well-known/xagent-verification.json` and the business API share one HTTPS origin, and that both version responses match the source commit used to build. The public release must also pass the official online submission validator described in [RELEASE.md](RELEASE.md).

The 2 MiB request limit and 100 snapshots / 100 experiments per session constrain individual sessions. They are not an account-wide traffic limit. Configure service-level rate limits and resource budgets for the public deployment. The 5,000-day maximum is a functional input limit, not a claim that every Cloudflare plan can execute it within its CPU allowance.

## Tests and offline verification

Run `uv sync --frozen` and `uv run pytest -q` from `source/` for Python behavior tests. The HTTP smoke scripts target the running Worker at `http://127.0.0.1:8787` or the public HTTPS origin. The offline CLI `python3 -m app.reproduce evidence.json` uses only the Python standard library and needs no server or network. See [validation](VALIDATION.md) for the complete commands.

The workbench and `/openapi.json` use same-origin resources. Swagger UI at `/docs` loads scripts and styles from jsDelivr and its icon from the FastAPI documentation site.

## Persistence and removal

Cloudflare session data resides in Durable Objects, not the Worker's ephemeral filesystem. There is no automatic expiry or public deletion endpoint in this version. Export evidence JSON before clearing local history or retiring a deployment. Deleting a browser cookie or rotating `SESSION_SECRET` removes access to earlier sessions; it does not delete their stored records. Cloud data removal is an administrator operation and must be planned separately from withdrawing the public route.

For local development, Wrangler manages Durable Object state under the generated bundle's `.wrangler` directory. Stop the dev server before removing that dedicated state or `.dev.vars`. Keep the session secret and state together when preserving local sessions.

A Worker redeployment preserves Durable Objects. Schema changes require an explicit migration plan. Keep earlier source versions available for historical evidence; never silently rewrite saved experiments.
