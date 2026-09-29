# Deployment status

Updated 2026-09-16. The application is publicly deployed for GitHub account KongkouKK on Vercel Hobby, for a personal, noncommercial demonstration.

- Source repository: [KongkouKK/life-exchange-rate-mcp](https://github.com/KongkouKK/life-exchange-rate-mcp).
- Production origin: [life-exchange-rate-mcp.vercel.app](https://life-exchange-rate-mcp.vercel.app).
- [API documentation](https://life-exchange-rate-mcp.vercel.app/docs), [health](https://life-exchange-rate-mcp.vercel.app/health), and [deployment proof](https://life-exchange-rate-mcp.vercel.app/.well-known/xagent-verification.json) were checked successfully. Use the proof or health response to read the currently deployed Git revision; a documentation commit is not the deployment's source of truth.
- Canonical MCP endpoint: `https://life-exchange-rate-mcp.vercel.app/mcp/`. Current and legacy protocol initialization passed, and both modes listed and called all nine tools.

## Verification completed

The application and three deployment configuration checks passed together: **148 local tests**. The earlier `verification/summary.json` and `build-check.json` describe the original local stage (145 tests and its wheel); they remain historical evidence, not proof of a Vercel build.

The complete hosted run at **2026-09-16 06:40 UTC** passed protocol versions `2026-07-28` and `2025-11-25`. Each mode listed all nine tools, made 12 successful calls covering every tool, and rejected seven invalid inputs: unsupported event mode, unknown headline source, identical FX currencies, out-of-range lookback, a headline lacking numeric event values, conversion currency mismatch, and an invalid scenario multiplier.

Live ECB/Frankfurter FX observations and Fed RSS were fetched successfully. Policy-rate and energy tools used synthetic fixtures; this is not evidence of hosted live policy-rate or EIA calls. The observed FX chain covered event retrieval → ranking → personal impact → life-unit conversion. Rates changed from 16.0689 to 15.8648 JPY/SEK between September 8 and 15; the explicit synthetic 20,000 SEK travel profile needed **257.30 SEK / 1.29 work hours** to restore its earlier JPY purchasing power. The separately fetched Fed headline was not asserted to cause the move.

The [saved hosted run](verification/hosted-live-2026-09-16.json) includes health/proof responses before and after the calls, with the same expected source revision and production origin throughout. It is a historical record bound to the revision inside that JSON. Query the public deployment proof for the current revision, and capture fresh evidence when reviewing a later deployment.

An earlier hosted fixture run at 06:30 UTC used MCP SDK 2.2.0 and returned the fixed result **1,739.13 SEK / 8.70 work hours**. Its health request returned HTTP 200 in 406 ms and deployment proof returned HTTP 200 in 297 ms, without redirects and within a 10-second request timeout. The source revision matched the expected deployed revision, and proof origin, slug, and MCP URL matched the production configuration. These are measurements of that run, not a guarantee of future latency or cold-start behavior.

## Free plan and remaining submission work

Vercel Hobby is the selected free plan, subject to its personal/noncommercial terms and quotas. No paid upgrade is required for this demonstration. No EIA key is configured, so energy results use an explicitly labeled synthetic scenario fallback; live EIA validation remains unperformed. See [free deployment instructions](docs/DEPLOY_FREE.md).

Deployment does not complete contest submission. `submission.json` and `SUBMISSION.md` still need final review against the deployed proof, and `RIGHTS.md` requires the submitter's declarations. **No official contest pull request has been submitted.**
