# Life Exchange Rate MCP

## Capability

- **One-line description:** Translate structured macroeconomic changes into travel purchasing power, interest/fuel scenarios, work hours and user-defined everyday units.
- **Who it helps:** Agents explaining a market move for a user who supplies income, prices, budgets and relevant exposures.
- **Capability boundary:** Headlines trigger attention; numerical observations or labeled scenarios drive deterministic arithmetic. The service does not execute trades/payments, forecast prices, infer household income or claim that a separately retrieved headline caused a market move.

## Live API

- **API base URL:** https://life-exchange-rate-mcp.vercel.app
- **Health check:** https://life-exchange-rate-mcp.vercel.app/health
- **Deployment proof:** https://life-exchange-rate-mcp.vercel.app/.well-known/xagent-verification.json
- **MCP endpoint:** https://life-exchange-rate-mcp.vercel.app/mcp/ — including the trailing slash.
- **Authentication:** None for the public demonstration. No reviewer credential is required.
- **Rate limits / known limits:** No application-level per-user quota is implemented. Free Vercel Hobby quotas, cold starts and upstream availability can affect service. The configured function duration is at most 30 seconds. MCP uses stateless HTTP/JSON; no availability guarantee or paid capacity is claimed.
- **API contract:** [Live OpenAPI](https://life-exchange-rate-mcp.vercel.app/openapi.json), [checked-in OpenAPI](source/verification/openapi.json), [tool contracts](source/docs/TOOL_CONTRACTS.md).

## Source and reproducibility

- **Source repository:** https://github.com/KongkouKK/life-exchange-rate-mcp
- **Review commit:** `238954196ea6922d3cea2ae8acb914b0f4e01dbb`
- **Source submitted in this PR:** `source/`, including entry point, package files, fixtures, tests, `pyproject.toml`, `uv.lock` and configuration example.
- **Source comparison:** The public archive's 76 files matched the prepared source with text line-ending differences ignored; no missing, differing or extra paths were found. See [source verification](verification/source-verification-final.json).

From this submission directory, enter the runnable project and run:

```bash
cd source
uv sync --locked --extra dev
uv run --frozen python -m pytest
uv run --frozen uvicorn life_exchange_rate.main:app --app-dir source --host 127.0.0.1 --port 8000
```

From that runnable project directory, the standalone protocol checks are:

```bash
uv run --frozen python verification/smoke_mcp.py
uv run --frozen python verification/smoke_mcp.py --live-fx
```

Each smoke invocation starts and stops its own local server. The first uses fixtures; the second also requires live provider access.

**Deploy:** Import the public source repository into Vercel Hobby, keeping the repository root, FastAPI framework, root `app.py` and the checked-in dependency lock. Keep system environment variables exposed. Use the public production domain; no protected-preview access is needed. See [deployment instructions](source/docs/DEPLOY_FREE.md). The build requirement names Hatchling without a pinned build-backend version; its exact isolated Vercel version has not been verified.

**Version binding:** The app reads `VERCEL_GIT_COMMIT_SHA` and exposes it in both `/health` and the same-origin deployment proof. Both production endpoints were verified against the exact review commit above. A later source revision requires fresh version binding and verification before changing the review baseline.

## Verification

The project passed **148 local tests**. The hosted run at **2026-09-16 09:55:43 UTC** verified the declared review commit and passed:

- Current protocol `2026-07-28` and legacy protocol `2025-11-25`: each listed **9 tools**, passed **12 positive calls** covering all nine tools and rejected **7 invalid-input cases**.
- Live FX and official Fed RSS calls. Policy-rate and energy calls used clearly labeled synthetic fixtures; no live EIA test is claimed.
- Synthetic FX calculation: **1,739.13 SEK / 8.70 work hours** at the declared synthetic household inputs.
- Captured live FX calculation: source dates 2026-09-08 to 2026-09-15, rates 16.0689 to 15.8648 JPY/SEK; a synthetic 20,000 SEK budget produced **257.30 SEK / 1.29 work hours**. Later live observations can differ.

The public REST run at **2026-09-16 10:00:54 UTC** returned HTTP 200 with the expected fixture values/provenance and HTTP 422 for invalid input, with the same commit before and after the calls.

See the [repeatable verification runbook](verification/README.md), [complete hosted MCP record](verification/hosted-live-verification-final.json), [deterministic hosted record](verification/hosted-verification-final.json), and [REST record](verification/hosted-rest-verification-final.json).

**Safe error behavior:** Invalid REST input returns HTTP 422; unavailable live providers return sanitized HTTP 502 responses. Invalid MCP calls return tool-error results. Policy/energy `live_or_fixture` mode can return an explicitly labeled synthetic fallback; `live` mode does not present such a fallback as a successful observation.

These are application and deployment results. Official package validation is a separate pre-publication check; no unexecuted official check is represented as passed.

## Security and data handling

- **Data collected as request inputs:** Home currency/country, income, working hours, travel budget/currency, optional mortgage/savings/fuel exposures, everyday-unit prices, numeric events and pass-through assumptions.
- **Purpose and retention:** Calculate the requested result. The application has no database or application-level persistence of household profiles. Vercel processes API traffic; hosting-layer request/log retention follows its settings, and no verified retention interval is asserted. Review profiles are synthetic.
- **Outbound services:** Frankfurter's ECB FX route, ECB data API, Fed/ECB RSS, and EIA API when a key is configured. Providers receive currency/date/series queries, not the household income, mortgage or everyday-price profile.
- **Secrets:** Optional `EIA_API_KEY` belongs only in the deployment environment. No credentials are included in this submission. No EIA key is needed for the synthetic judging flow.
- **Known restrictions:** ECB daily reference rates are not executable retail quotes; retail fees/spreads are excluded. Interest/fuel pass-through is a stated scenario, with currency compatibility enforced. Free hosting and providers can be unavailable. [Provider terms](verification/licenses/PROVIDER-TERMS.md), attribution and third-party exceptions remain applicable.

## Support

- **Submitter:** kongkoukk
- **GitHub:** [KongkouKK](https://github.com/KongkouKK)
- **Public contact:** haozlee1994@gmail.com
- **License / rights:** [RIGHTS.md](RIGHTS.md) records the submitter's authorized program review/archive/publishing declaration and preserves third-party terms. No general-purpose first-party open-source license has been selected.
