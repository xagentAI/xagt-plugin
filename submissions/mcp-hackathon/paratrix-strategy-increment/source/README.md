# Running the application and using the API

Strategy Increment uses complete daily simulated equity curves to compare a baseline, a fixed-initial-allocation portfolio containing a candidate, and a cash control. The workbench, API, and offline reproduction tool use one calculation engine.

[Research workbench](https://strategy-increment.raspy-boat-dbb0.workers.dev/) · [API documentation](https://strategy-increment.raspy-boat-dbb0.workers.dev/docs) · [Health and source version](https://strategy-increment.raspy-boat-dbb0.workers.dev/health)

## Local Worker startup

Install Python 3.13 or 3.14, Node.js 22 or later, and uv 0.12.3 or later. Run from this directory:

```bash
python3 scripts/build_worker.py
cd runtime/worker-bundle
npm ci
uv run --locked pywrangler dev --local
```

Open the [Chinese-language workbench](http://127.0.0.1:8787). Interactive API documentation is at `/docs`; the schema is at `/openapi.json`. API descriptions and messages are in English. The Worker toolchain is pinned under `workers/`; the builder creates its runnable project under ignored `runtime/worker-bundle`. Deployment commands and configuration are in the [deployment guide](docs/DEPLOYMENT.md).

## Complete an experiment

1. Load A/B from the example menu or upload two simulated equity JSON files.
2. Check dates, currency, costs, and initial valuation. Optionally select a subinterval whose boundaries are existing valuation points.
3. Choose facts-only comparison or supply all four research criteria.
4. Inspect the three scenarios, individual differences, and equity/drawdown paths.
5. Download an evidence package, or change the conditions to create a derived experiment. The original record remains unchanged.

The five examples cover AIMM weight variants, a duplicated baseline, a cash control, one missing day, and a return/drawdown tradeoff. See [sample provenance](fixtures/README.md) for sources and construction. Examples and JSON imports need no external service credentials.

## Checks and reproduction

Run in a second terminal from `source/`. The root `pyproject.toml` and `uv.lock` define the CPython test and verification environment. The HTTP checks target the running local Worker:

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check app tests scripts worker.py
uv run python scripts/smoke.py --base-url http://127.0.0.1:8787
uv run python -m app.reproduce runtime/smoke-evidence.json
```

The reproduction command reads a local file. `verified: true` means the hashes and recomputed result match. It uses the method version recorded in the evidence; [METHOD.md](docs/METHOD.md) explains data provenance, model assumptions, and historical interpretation.

Independently reproduce the supplied example:

```bash
python3 -m app.reproduce ../verification/worker-evidence.json
```

This uses only the Python standard library and requires no running service or network connection.

## Inputs and endpoints

The [machine contract](docs/IMPLEMENTATION-CONTRACT.md) defines input fields and responses. The `baseline` and `candidate` values returned by `GET /v1/demo-cases/aimm-weight` can each be saved as an import template. Inputs need complete daily UTC valuations, a separate initial valuation, no external cash flows, and a stated cost model. Invalid data produces field-specific errors.

| Endpoint | Purpose |
| --- | --- |
| `GET /v1/demo-cases`, `/v1/demo-cases/{id}` | Example catalog and inputs |
| `POST /v1/data-snapshots` | Normalize and save an immutable input |
| `POST /v1/comparison-inputs/validate` | Check comparability before creating an experiment |
| `POST /v1/experiments` | Revalidate, calculate, and save atomically |
| `GET /v1/experiments`, `/v1/experiments/{id}` | Session history and experiment details |
| `GET /v1/experiments/{id}/evidence` | Reproducible JSON package |
| `GET /v1/source-status` | Source configuration and verification state |
| `POST /v1/nexus/import` | Return `source_unavailable`; external Nexus imports are disabled |

The Worker serves examples and simulation JSON imports. External Nexus imports are disabled. Input provenance and complete-curve requirements are described in [adapter documentation](app/adapters/README.md).

## Sessions and data

Clients preserve a signed cookie to access their experiments. Cookies last 30 days. The Worker stores records in session-scoped SQLite-backed Durable Objects. Records have no automatic expiry-deletion policy and are retained and cleaned by the operator. Cookie expiry does not delete stored records. After cookie deletion, a new session cannot recover the old session's records; export evidence packages for long-term retention.

Limits are 100 snapshots and 100 experiments per session, 2 MiB per request, and 5,000 daily points per curve. Runtime data is excluded from the source package. See [deployment](docs/DEPLOYMENT.md) for persistence, HTTPS, and operational configuration.

## Source layout

| Location | Responsibility |
| --- | --- |
| `app/domain/engine.py` | Input validation, three paths, and four criteria |
| `app/adapters/` | Examples and recorded AIMM simulation inputs |
| `app/main.py` | HTTP endpoints, session boundaries, and experiment orchestration |
| `app/workers_storage.py` | Session-scoped SQLite Durable Objects and chunked record persistence |
| `app/storage.py` | Storage exceptions and experiment-finalization rules |
| `worker.py`, `workers/`, `wrangler.jsonc` | Cloudflare entrypoint, pinned build tools, and deployment configuration |
| `app/evidence.py`, `app/reproduce.py` | Evidence export and offline reproduction |
| `web/` | Chinese-language single-page workbench |
| `fixtures/` | Recorded examples and provenance summaries |
| `tests/`, `scripts/` | Behavior tests, example generation, HTTP checks, and packaging |
| `docs/` | Product, method, architecture, contract, and operations |

Maintainer: [karpak-labs](https://github.com/karpak-labs) · [MIT](../LICENSE) · [Third-party and data provenance](../RIGHTS.md) · [Support](https://github.com/karpak-labs/strategy-increment/issues)
