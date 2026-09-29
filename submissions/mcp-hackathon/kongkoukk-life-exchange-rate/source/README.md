# Life Exchange Rate MCP

**Every headline has a price. See yours.**

Translate structured macroeconomic events into travel purchasing power, mortgage/savings and fuel scenarios, work time, and user-defined everyday units. Headlines trigger attention; **only structured numeric observations drive calculations**. Wages, budgets, prices and pass-through assumptions come from explicit inputs or clearly labeled demonstration defaults.

## Public demo

The application is deployed on Vercel Hobby for a personal, noncommercial demonstration:

- [Interactive API documentation](https://life-exchange-rate-mcp.vercel.app/docs)
- [Health and deployed source revision](https://life-exchange-rate-mcp.vercel.app/health)
- [Deployment verification proof](https://life-exchange-rate-mcp.vercel.app/.well-known/xagent-verification.json)
- MCP endpoint: **https://life-exchange-rate-mcp.vercel.app/mcp/**, including the trailing slash. Connect with an MCP client; this is not a web page.

On 2026-09-16, hosted health, deployment proof, and complete MCP checks passed in current and legacy protocol modes. Each mode called all nine tools successfully (12 positive calls) and rejected seven invalid inputs. The run fetched live ECB/Frankfurter FX observations and Fed RSS; policy-rate and energy calls used explicitly synthetic fixtures. The [saved hosted evidence](verification/hosted-live-2026-09-16.json) records that deployment's revision, while the deployment proof reports the current revision. See [deployment status](DEPLOYMENT_STATUS.md) and the [verification runbook](verification/README.md).

## Run locally

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```powershell
uv sync --locked --extra dev
uv run --frozen python -m pytest
uv run --frozen uvicorn life_exchange_rate.main:app --app-dir source --host 127.0.0.1 --port 8000
```

Open [API docs](http://localhost:8000/docs), [health](http://localhost:8000/health), or [demo radar](http://localhost:8000/v1/radar/demo). The canonical MCP endpoint is **http://localhost:8000/mcp/**, including the trailing slash. It is a protocol endpoint, not a web page.

For local configuration, copy `.env.example` to `.env` and add `--env-file .env` to the Uvicorn command. Environment files are not loaded automatically. Never commit API keys. Vercel Git deployments use the platform's actual `VERCEL_GIT_COMMIT_SHA` and production domain automatically. Self-hosted deployments can set `PUBLIC_BASE_URL` and `REVIEW_COMMIT` explicitly. The MCP host allowlist uses the resolved public origin; `/health` and `/.well-known/xagent-verification.json` report the same source revision. `dev-local` is a development placeholder. See [free deployment instructions](docs/DEPLOY_FREE.md).

## End-to-end demo

```powershell
# Reproducible synthetic judging scenario, no network or key required:
uv run --frozen python -m life_exchange_rate.demo
# Actual ECB/Frankfurter observations -> ranking -> SEK/JPY travel -> work/life units:
uv run --frozen python -m life_exchange_rate.demo --live
# Real MCP HTTP client in current and legacy protocol modes:
uv run --frozen python verification/smoke_mcp.py --live-fx
```

The smoke script starts and stops a local server automatically. Without `--live-fx`, it checks the offline chain and explicitly records the live FX/RSS calls as skipped. Evidence is saved in `verification/mcp-smoke.json` and `verification/end-to-end-demo.json`.

In the fixed synthetic scenario, 20,000 SEK bought 300,000 JPY at 15 JPY/SEK and buys 276,000 JPY at 13.8. Restoring the original purchasing power needs **1,739.13 SEK**, equivalent to **8.70 work hours**, **38.65 coffees**, or **12.42 lunches** at the declared demonstration income and prices. These alternatives are equivalents of the same amount, not additional expenses. They are not current market data or the user's finances.

The hosted live capture on **2026-09-16** retrieved ECB/Frankfurter rates of **16.0689 → 15.8648 JPY/SEK** for **September 8 → 15**. For a synthetic person with a 20,000 SEK travel budget, restoring the earlier JPY purchasing power required **257.30 SEK**, equivalent to **1.29 work hours**, **5.72 coffees**, or **1.84 lunches** using explicit inputs of 32,000 SEK monthly income, 160 work hours, 45 SEK per coffee, and 140 SEK per lunch. These profile values are demonstration inputs, not the user's finances or observed retail prices; the reference-rate comparison excludes exchange fees and spreads. A Fed headline was fetched separately to test the headline interface, with no claim that it caused the FX move. [Capture and calculation trace](verification/hosted-live-2026-09-16.json).

## Data and guarantees

- Live FX uses Frankfurter's dedicated ECB route, correct calendar lookback selection and a rolling log-return anomaly score. Every score reports its horizon, reference sample count, mean, sample volatility and fallback reason. See `docs/FX_ANOMALY.md`.
- Policy rates use the official ECB daily euro-area deposit facility series. Events apply only to matching EUR exposures.
- Energy uses EIA API v2 Brent daily spot prices. `EIA_API_KEY` is needed only for live energy. No configured key means a labeled synthetic fallback in `live_or_fixture` mode.
- Both structured adapters accept `live`, `fixture`, and `live_or_fixture`. Live mode fails when data are unavailable; fixture/fallback events have `confidence=scenario`, `metadata.synthetic=true`, no official evidence URL, fixed source dates, and a stated fallback reason when applicable.
- Fed/ECB RSS returns headline triggers with `requires_quantification=true`; a headline cannot satisfy the numeric event schema.
- Inputs reject nonfinite values, inconsistent price changes and nonpositive FX/oil observations. Rate calculations require matching currency scope; foreign-currency mortgages are excluded from home-currency totals.
- Impact output preserves event provenance and source dates alongside formulas. Retail FX fees/spreads are excluded. Fuel and interest pass-through are explicit scenarios, not forecasts.

## Interfaces

Nine MCP tools cover events, headlines, live FX, policy rates, energy, ranking, translation, life-unit conversion and scenario comparison. `docs/TOOL_CONTRACTS.md` lists each tool and REST route. The REST OpenAPI contract is available at `/openapi.json` and is checked in at `verification/openapi.json`.

Tests use deterministic HTTP fixtures and exercise real MCP tool serialization. The separate smoke script proves the actual HTTP mount and protocol negotiation. See `verification/README.md`, `verification/MCP_SMOKE.md`, `docs/DATA_SOURCES.md`, and `docs/JUDGE_DEMO.md`.

## Submission status

Source is published at [KongkouKK/life-exchange-rate-mcp](https://github.com/KongkouKK/life-exchange-rate-mcp). The application passed 148 local tests and the hosted checks described above. Deployment is on the free Vercel Hobby plan, within its personal/noncommercial terms and usage quotas. No EIA key is configured: energy demonstration results use the explicitly labeled synthetic scenario fallback, and no live EIA verification is claimed.

Contest submission remains separate from deployment. `submission.json` and `SUBMISSION.md` still require final submission review; `RIGHTS.md` is a draft requiring the submitter's declarations. No official contest pull request has been submitted.
