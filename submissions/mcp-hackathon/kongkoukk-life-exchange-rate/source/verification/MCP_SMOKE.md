# MCP v2 verification

## SDK and mount

Verified against installed **mcp 2.2.0**, the current stable version shown on [PyPI](https://pypi.org/project/mcp/), on 2026-09-14.

The server imports `MCPServer` from `mcp.server`. Transport settings belong on `streamable_http_app()`. FastAPI's parent lifespan starts `mcp.session_manager.run()`, because mounting a child ASGI application does not start its lifespan. `app.mount("/mcp", ...)` with `streamable_http_path="/"` serves the canonical endpoint **`/mcp/`**. These match the [official migration guide](https://py.sdk.modelcontextprotocol.io/migration/) and [ASGI mounting documentation](https://py.sdk.modelcontextprotocol.io/run/asgi/).

The public hostname and origin are allowlisted from `PUBLIC_BASE_URL`; local development hosts are also accepted. Other hosts/origins are rejected. The application version is authoritative in `/health`, verification metadata and MCP server identity; health and verification return the same `REVIEW_COMMIT`. `dev-local` remains explicit until a real review commit is supplied. [Official deployment guidance](https://py.sdk.modelcontextprotocol.io/run/deploy/)

## Executed live smoke

At **2026-09-14 15:02:21 UTC**, `verification/smoke_mcp.py --live-fx` completed successfully against a real Uvicorn subprocess serving the FastAPI application at `http://127.0.0.1:53644/mcp/`. The official SDK `Client` connected over Streamable HTTP; this run used neither an in-memory transport nor mocked MCP responses. The script confirmed the server stopped after completion. Full records are in [mcp-smoke.json](mcp-smoke.json) and [end-to-end-demo.json](end-to-end-demo.json).

| Client mode | Negotiated protocol | Tool discovery | Positive calls | Invalid calls |
| --- | --- | --- | --- | --- |
| `auto` | `2026-07-28` | All 9 tools | All 9 tools; 12 calls passed | 7 rejected as expected |
| `legacy` | `2025-11-25` | All 9 tools | All 9 tools; 12 calls passed | 7 rejected as expected |

The positive calls covered live Federal Reserve RSS, live ECB-filtered Frankfurter FX observations, synthetic macro events, policy-rate and energy fixture modes, ranking, translation, life-unit conversion, and explicit zero-pass-through scenarios. It also verified the fixed Japan-travel example: **20,000 SEK**, **15.0 → 13.8 JPY per SEK**, **1,739.13 SEK** extra budget and **8.70 work hours**. Income and unit prices are explicitly synthetic profile inputs.

Negative checks covered unsupported modes, unknown headline sources, identical FX currencies, out-of-range lookback, headline-only translation, mismatched conversion currency and invalid scenario multipliers. `auto` and `legacy` use the [official client's protocol negotiation modes](https://py.sdk.modelcontextprotocol.io/protocol-versions/).

## Recorded official-event demo

The retained run retrieved **16.1127 → 15.8248 JPY per SEK**, observed on **2026-09-07 → 2026-09-14**. The observed move was **-1.7868%**, with a signed anomaly score of **-1.6794** from 252 preceding reference windows. Source URLs, source dates, retrieval time and anomaly statistics are retained in the event and impact records.

The FX event received priority **73.9**, position **2** among the observed FX event and two explicitly synthetic comparison events. The unmatched EUR policy event has user relevance zero. Applying the supplied **20,000 SEK** travel budget produced:

- **363.86 SEK** additional budget to preserve the original JPY purchasing power;
- **1.82 work hours**, using supplied monthly income of 32,000 SEK and 160 work hours;
- **4.55 beers**, **8.09 coffees**, or **2.60 lunches**, at supplied prices of 80, 45 and 140 SEK.

The trace evaluates `20000 × 16.1127 / 15.8248 − 20000`. Retail fees and spreads are excluded. Personal income and local prices are explicitly illustrative inputs, not actual user finances or market price measurements.

The separately fetched Fed headline was *Minutes of the Board's discount rate meetings on July 20 and July 29, 2026*, published `2026-08-25T18:00:00Z`. It retains `requires_quantification=true` and was rejected as a translation input. No causal link to the FX move is asserted: only independent structured observations drive the calculation.

An earlier offline run passed both modes with seven positive fixture/calculation calls and seven expected input rejections each. The retained JSON artifacts now contain the later live successful run.

## Reproduce

```console
uv run python verification/smoke_mcp.py
uv run python verification/smoke_mcp.py --live-fx
```

The first command runs the reproducible flow. The second additionally makes positive official RSS and ECB-filtered live FX calls in both protocol modes, then records **official numeric FX event → ranked radar → JPY/SEK trip impact → work/life units**. The separately fetched Fed headline is contextual; the record expressly avoids asserting that it caused the FX move.

Results are written to `verification/mcp-smoke.json` and `verification/end-to-end-demo.json`; `--output-dir` can preserve an additional run. Live failures record a redacted nested traceback and produce a nonzero exit code. The script reports skipped live calls explicitly and never substitutes synthetic data for a claimed live FX observation.

## Regression checks

The original dependency-installed baseline was **7 passed, 1 failed**: two test contexts attempted to restart one single-use SDK session manager. API tests now share one application lifespan. MCP tests additionally exercise all nine tools through the official SDK, input rejection, explicit pass-through settings, and sanitized provider errors. REST tests cover canonical discovery metadata, provider modes, headline rejection, and Host/Origin restrictions.

The final regression suite passes 145 tests. Policy-rate ranking now excludes unmatched currency exposures, and malformed nonfinite JSON inputs return a safe 422 validation response.
