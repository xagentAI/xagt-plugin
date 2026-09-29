# Verification runbook

```powershell
uv sync --locked --extra dev
uv run --frozen python -m pytest
uv run --frozen python verification/smoke_mcp.py
uv run --frozen python verification/smoke_mcp.py --live-fx
uv run --frozen python verification/generate_fixtures.py
```

The smoke script owns a temporary loopback Uvicorn process and stops it on success/failure. Default mode proves the synthetic MCP flow without external requests. `--live-fx` additionally exercises actual official RSS and FX; a live failure is recorded as failure, never as a successful fallback. `MCP_SMOKE.md` describes the latest retained run; machine evidence is in `mcp-smoke.json` and `end-to-end-demo.json`.

`generate_fixtures.py` regenerates OpenAPI, the fixed FX request/response, invalid input and policy/energy fixture requests/responses, and the offline ranked demo. `tests/test_verification.py` checks the saved contract and fixed core response. Provider fixture dates are synthetic; captured live source dates and retrieval times remain distinct.

Run the app with `uv run --frozen uvicorn life_exchange_rate.main:app --app-dir source --port 8000`. Check `/health`, `/.well-known/xagent-verification.json`, `/openapi.json`, `/v1/events/demo`, `/v1/radar/demo`, and `/mcp/` using a real MCP client. A raw browser GET is not a tool call. POST `fixtures/fx-request.json` to `/v1/translate` and compare the response to `fixtures/fx-response.json`.

## Hosted deployment and revision binding

The public deployment is **https://life-exchange-rate-mcp.vercel.app**, sourced from [KongkouKK/life-exchange-rate-mcp](https://github.com/KongkouKK/life-exchange-rate-mcp). Read `/health` and `/.well-known/xagent-verification.json` for the currently deployed source revision. Vercel Git deployments use the actual `VERCEL_GIT_COMMIT_SHA` and production domain automatically. Self-hosted deployments can instead set `REVIEW_COMMIT` to the reviewed Git SHA and `PUBLIC_BASE_URL` to the public origin. Do not submit `dev-local` or invented deployment URLs.

Health and proof share package version and commit. Finalize `submission.json` and `SUBMISSION.md` from the verified deployed values and rerun hosted checks after deploying any source change. The MCP host allowlist derives from the resolved public origin while retaining loopback for local use. `RIGHTS.md` still requires the submitter's declarations; no official contest pull request has been submitted.

The initial hosted run on 2026-09-16 at 06:30 UTC passed health and proof checks without redirects, within a 10-second timeout, and with matching revision, origin, slug, and MCP URL. MCP SDK 2.2.0 successfully initialized protocol versions `2026-07-28` and `2025-11-25`; each listed all nine tools and passed calls to `get_macro_events`, `translate_event_to_life`, and `convert_to_life_units`. Invalid event and conversion inputs were rejected. The fixture result was 1,739.13 SEK / 8.70 work hours with a calculation trace. This initial hosted run used only synthetic data and did not test live providers or call all nine tools.

The subsequent [complete hosted run at 06:40 UTC](hosted-live-2026-09-16.json) passed both protocol versions. Each mode made 12 successful calls covering **all nine tools** and rejected **seven invalid inputs**: unsupported event mode, unknown headline source, identical FX currencies, out-of-range lookback, a headline lacking numeric event values, conversion currency mismatch, and an invalid scenario multiplier. Live ECB/Frankfurter FX and Fed RSS calls succeeded; policy-rate and energy calls explicitly used fixture mode. Health and deployment proof matched the expected source revision before and after the calls. The saved JSON is bound to its recorded historical revision; the current deployed revision must be read from the public proof.

That run's observed FX window was 2026-09-08 through 2026-09-15, with 16.0689 → 15.8648 JPY/SEK. The explicit synthetic profile's 20,000 SEK travel budget required an additional 257.30 SEK, equivalent to 1.29 work hours, 5.72 coffees, or 1.84 lunches at the supplied income and prices. The record preserves the inputs, source dates, retrieval time, ranking, calculation trace, and unit conversion. The separately fetched Fed headline is not claimed to cause the FX move; only numeric FX observations drive that calculation.

The full application, including deployment configuration, passed 148 local tests. Earlier retained `summary.json`, `build-check.json`, and local MCP records describe their own historical runs; they do not by themselves prove hosted behavior.

EIA live validation requires `EIA_API_KEY`. Automated EIA success/error cases use mocked official-shaped responses; missing-key fallback is tested explicitly. No live EIA result should be claimed unless a keyed request was actually run.


## Hosted review calls

Run from the project root. These commands reproduce the checks; their presence is not a saved execution result:

```bash
API_ORIGIN='https://life-exchange-rate-mcp.vercel.app'
curl --fail --silent --show-error "$API_ORIGIN/health"
curl --fail --silent --show-error "$API_ORIGIN/.well-known/xagent-verification.json"
curl --fail --silent --show-error "$API_ORIGIN/v1/translate" --header 'Content-Type: application/json' --data-binary @verification/fixtures/fx-request.json
curl --silent --show-error --write-out '\nHTTP %{http_code}\n' "$API_ORIGIN/v1/translate" --header 'Content-Type: application/json' --data-binary @verification/fixtures/invalid-request.json
```

The capability fixture expects 1,739.13 SEK / 8.70 work hours. The invalid request expects HTTP 422. Connect a real MCP client to `https://life-exchange-rate-mcp.vercel.app/mcp/`, with the trailing slash, to check initialization and tools; a browser GET is not a tool call. Capture fresh hosted evidence after each reviewed deployment; localhost records alone are insufficient. In Windows PowerShell, set `$API_ORIGIN = 'https://life-exchange-rate-mcp.vercel.app'` and use `curl.exe` when `curl` is aliased.
