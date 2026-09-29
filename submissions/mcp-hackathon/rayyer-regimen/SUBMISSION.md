# Regimen

**Track: Open Innovation Challenge.**

A Sharpe ratio is an estimate. Regimen tells you whether it is a fact.

## Capability

- **One-line description:** Given a trading strategy's equity curve, decide whether the measured performance is distinguishable from luck, and which market conditions the edge actually lives in.
- **Who it helps:** Any agent or person about to act on a performance number — sizing a strategy, listing it, allocating to it, or repeating its Sharpe ratio to someone else. An agent asked "is this strategy any good?" currently has no way to answer beyond restating the marketing.
- **Capability boundary:** Regimen reads a track record and reports what the evidence supports. It does **not** trade, hold funds, custody keys, or sign anything. It does **not** inspect smart contracts, score wallets or transactions, detect scams, or perform security, audit or compliance analysis of any kind. It does not forecast returns, and a favourable verdict is a statement about evidence, never a prediction.

### The problem this solves

A strategy publishes a Sharpe ratio of 2.4 over six weeks and a 58% win rate over 40 trades. Both numbers are arithmetically correct. Neither is evidence.

A Sharpe ratio computed from a short, skewed, fat-tailed sample carries an error bar wide enough to swallow the claim. Forty trades cannot separate a 58% edge from a coin. And once a strategy has been re-tuned twenty times, the best configuration looks good for the same reason the tallest of twenty random people is tall. The mathematics for handling all three has existed since 2012 and is almost never applied, because it takes more than dividing a mean by a standard deviation.

This is not a prompt-only demo, and it is not a wrapper. A language model asked to judge a Sharpe ratio will produce a confident paragraph; it will not compute a Probabilistic Sharpe Ratio corrected for sample skewness and kurtosis, run a seeded stationary bootstrap, derive a minimum track record length, or run a permutation test over regime buckets. Regimen does those deterministically, returns the numbers with the reasoning, and reproduces them exactly on every call.

Real output from the live service, on a curve whose **annualised Sharpe is 3.72**:

```
verdict      weak
confidence   92.3% that the true Sharpe exceeds 0
95% interval [-0.033, +0.462]        zero is still inside
track record 59 periods; 78 needed for significance at 95%
```

A dashboard would have printed `3.72` and stopped. The same call's self-attack reports that **6.8% of simulated strategies with no edge at all, matched for length and volatility, score at least as well**.

### What it computes

1. **Significance.** Probabilistic Sharpe Ratio (Bailey & López de Prado, 2012) — the probability the true Sharpe exceeds a benchmark given sample length, skewness and kurtosis. Minimum Track Record Length — how many periods would be needed before the claim could be made at all. Deflated Sharpe Ratio (2014) — the same statement corrected for how many configurations were tried first. A seeded stationary bootstrap (Politis & Romano, 1994) interval that preserves serial dependence.
2. **Regime attribution.** Each period's return joined to the market conditions that held on that UTC date — volatility, funding, open interest, positioning, sentiment, trend state — read point-in-time, so nothing in a bucket could only have been known afterwards. Each factor carries a permutation test on the between-bucket dispersion of performance, because slicing a return series eight ways guarantees a flattering subset.
3. **Self-attack.** Controls whose answer is known in advance: the strategy's own returns with the mean removed (true Sharpe exactly zero, so a correct engine must grade it near 50%), and a simulated population of edgeless strategies matched for length and volatility. Published including when a control fails.
4. **Divergence check.** Where a source publishes its own figures, Regimen recomputes them from the equity curve and reports the difference.

### Data sources

The engine is written against a domain model — a track record, a regime series — never against a vendor's response shape, so a data source is a thin adapter.

- **`inline`** — bring your own equity curve, from any venue, backtest or spreadsheet. No credentials.
- **`olaxbt-nexus`** — an OlaXBT Nexus strategy. The adapter reads the strategy's equity curve, trades and published metrics, and reads eight market-condition factors per date with an explicit `as_of`, which is what makes the regime attribution free of lookahead. It paces calls under a token bucket below the published 80/minute ceiling and caches every immutable past-dated read, because a regime map wants hundreds of point-in-time reads. Activated by supplying a Nexus key in the `x-nexus-key` header.

## Live API

- **API base URL:** `https://regimen-nu.vercel.app/api/v1`
- **Health-check URL:** `https://regimen-nu.vercel.app/api/health`
- **Deployment proof:** `https://regimen-nu.vercel.app/.well-known/xagent-verification.json`
- **MCP endpoint:** `https://regimen-nu.vercel.app/mcp` — protocol revision `2026-07-28`
- **MCP Registry:** published as `io.github.RaYYeR220/regimen` v1.0.0 — `curl https://registry.modelcontextprotocol.io/v0/servers?search=regimen`
- **API contract:** OpenAPI 3.1 at `https://regimen-nu.vercel.app/api/v1/openapi.json`, generated from the same schemas the routes validate against, so the published contract cannot drift from the enforced one. Source: `source/src/lib/openapi.ts`.
- **Authentication:** None for the `inline` source — every verification step below runs with no credentials. The `olaxbt-nexus` source takes a caller-supplied key in the `x-nexus-key` header. Keys are read per request, never persisted, never logged; where a key must be identified for rate limiting or cache partitioning only a non-reversible fingerprint is used.
- **Rate limits / known limits:** Anonymous traffic is limited to 20 requests per minute per source address (in-memory, per instance, best effort — it is a courtesy limit, not a security control). A caller supplying their own Nexus key is not subject to it. A regime map reads at most 45 dates per request, because each date costs five point-in-time upstream reads and the upstream allows 80 a minute; past dates are immutable and cached, so repeating the call widens coverage. Bootstrap resamples are capped at 20,000 and null simulations at 20,000 per request.

### Endpoints

| Method | Path | What it answers |
|---|---|---|
| `POST` | `/api/v1/evaluate` | Is this track record distinguishable from luck? |
| `POST` | `/api/v1/regime-map` | Which market conditions is the edge concentrated in? |
| `POST` | `/api/v1/self-attack` | Why should I believe the verdict? |
| `GET` | `/api/v1/status` | Upstream reachability, cache occupancy, demo-key availability. |
| `GET` | `/api/v1/openapi.json` | The machine-readable contract. |
| `GET` | `/api/health` | Liveness and the exact build commit. |

Every response is `{ data, meta }` or `{ error, meta }`. `meta` carries a request id, the build commit, and which credential mode served the request.

### MCP surface

Four tools — `regimen_evaluate_track_record`, `regimen_regime_map`, `regimen_self_attack`, `regimen_describe_factors`. Each advertises an `outputSchema` and returns validated `structuredContent`; each is annotated `readOnlyHint: true` and `destructiveHint: false`, because nothing here writes, trades or signs; each takes a `detail` switch so an agent can ask for the verdict and its reasoning rather than every bucket. Failures come back as tool-execution errors carrying the machine-readable code, so a model can correct itself instead of guessing.

Three resources — `regimen://methodology` (the statistics in full), `regimen://evidence-tiers` (the exact grading thresholds), and the template `regimen://factor/{key}` whose `key` argument supports `completion/complete`. One prompt — `validate_strategy`, the full review in the right order.

The server is stateless as revision `2026-07-28` requires: no `initialize` handshake, no session id, `ttlMs`/`cacheScope` on every cacheable result, and `GET /mcp` answered with `405` so a client can tell it apart from a legacy HTTP+SSE server.

### Web surface

`https://regimen-nu.vercel.app` runs the product rather than describing it: the landing page's figures are produced by a server-side call to this deployment's own `/api/v1/evaluate` and `/api/v1/self-attack` against the published demo curve, so the page cannot quietly disagree with the engine, and if those calls fail it says so instead of showing stale numbers. It carries an interactive panel where a visitor runs an analysis in the browser — including a one-click path to the refusal case, which renders as a deliberate refusal rather than an error. `/methodology` publishes the full statistical method, the same text the `regimen://methodology` MCP resource serves.

## Source and reproducibility

- **Source repository:** https://github.com/RaYYeR220/regimen
- **Review commit:** `c5c3a0b5f719aed5418c9738fd1002b9d20eef71`
- **Source submitted in this PR:** `source/` — the complete repository at that commit, including `package.json`, `pnpm-lock.yaml`, the test suites and the evaluation suite. 68 files.
- **Run locally:** `pnpm install && pnpm dev` → `http://localhost:3000`. No credentials needed for the `inline` source.
- **Run tests:** `pnpm test` — **409 tests**, of which 370 cover the statistics core. `pnpm typecheck` runs TypeScript in strict mode with `noUncheckedIndexedAccess`.
- **Run the evaluation:** `pnpm eval` — regenerates `EVAL.md` and `eval-results.json` byte-for-byte.
- **Deploy:** any Node 20+ host. The deployed instance runs on Vercel, built directly from the GitHub repository.
- **Version binding:** the commit reported by `/api/health` and `/.well-known/xagent-verification.json` is **read from the platform's build metadata at request time, never hard-coded**. Whatever commit was built is what both endpoints report, so the declared commit and the running service cannot drift apart. `REVIEW_COMMIT` exists only as an escape hatch for self-hosting outside a git-aware build, and the value is validated as a 40-character SHA rather than trusted.

### Test evidence

The statistics core carries known-answer tests for the Probabilistic Sharpe Ratio, Minimum Track Record Length, the Deflated Sharpe Ratio, skewness, kurtosis, Wilson intervals and drawdown, whose reference values were generated independently of this implementation and whose arithmetic is written out in comments. `normalCdf` is asserted to ~1e-14 relative accuracy out to Φ(−37) against SciPy's Cephes `ndtr`. A negative-control test across 20 seeds confirms a zero-mean series clears 95% confidence on 2 of 20 runs — the nominal size — while the matching positive-mean series clears it on 20 of 20. A package-wide sweep drives hostile inputs through every public function and asserts no success payload contains `NaN` or `Infinity` anywhere.

### The graded evaluation, including what it failed

`EVAL.md` is a pre-registered evaluation: 82 synthetic strategies with known ground truth, fixed before the engine was run against them.

**It fails three of its six targets, and they are published rather than tuned away.**

| Measure | Target | Measured |
|---|---|---|
| False positive rate | ≤ 0.05 | **0.056 (2/36)** — missed |
| Power | ≥ 0.80 | 0.800 (12/15) |
| Correct refusals on degenerate input | 1.00 | 1.000 (8/8) |
| Restraint on unprovable real edges | ≥ 0.90 | **0.667 (10/15)** — missed |
| Regime detection | ≥ 0.75 | **0.250 (1/4)** — missed |
| Regime false positives | ≤ 0.05 | 0.000 (0/4) |

The findings are the useful part:

- Both false positives are the same mechanism: a negatively-skewed distribution on a short window whose crash component has not arrived yet. The non-normality correction is driven by the *sample* third and fourth moments, and at 40–60 observations those carry almost no information — so the exact pattern the correction exists to catch is the one it walks into. The engine now says this explicitly in its own reasoning whenever a sample is too short for those moments to mean anything.
- The regime test originally used the best-minus-worst Sharpe spread, which sees only two buckets and inflates with bucket count. On a planted effect it could not separate signal from the null at all — planted spread 0.493 against a null control's 0.491. It was replaced with an observation-weighted between-bucket variance, which moved the planted cases' p-values from 0.022/0.073/0.092/0.229 to 0.010/0.054/0.069/0.275 while the unplanted controls stayed quiet at 0.18–0.91. A material improvement, still short of the pre-registered target, so the target stands as missed.

`CLAIMS.md` tags every public statement by evidence tier with a way to check it, including an explicit not-claimed list. `MOCKS.md` draws the exact line between real third-party data and simulated quantities.

### MCP conformance

`npx @modelcontextprotocol/conformance@alpha server --url <url>` against a local build: **36 checks pass, 23 fail.** Passing: protocol negotiation, `ping`, `tools/list`, `resources/list`, `prompts/list`, and DNS-rebinding protection. Every failure is a scenario exercising the suite's own reference-server fixtures — named test tools, sampling, logging, image and audio content, resource subscriptions — none of which Regimen implements. The raw counts are stated rather than summarised as a pass, because a conformance claim that hides its denominator is worth nothing. The DNS-rebinding scenario reports failure against any non-localhost URL by construction, which its own description states, so it is meaningful only against a local build.

## Verification

`verification/README.md` in this directory is the full script, runnable with no credentials. In summary:

- **Health-check result:** `GET https://regimen-nu.vercel.app/api/health` → `{"status":"ok","commit":"c5c3a0b5f719aed5418c9738fd1002b9d20eef71","service":"regimen","slug":"rayyer-regimen","uptimeSeconds":<n>}`
- **Deployment proof:** `GET https://regimen-nu.vercel.app/.well-known/xagent-verification.json` → `{"schemaVersion":1,"slug":"rayyer-regimen","commit":"c5c3a0b5f719aed5418c9738fd1002b9d20eef71"}`
- **Capability call:** `POST /api/v1/evaluate` with the 60-point curve in `verification/README.md` returns `evidence.tier: "weak"` on an annualised Sharpe of 3.72, `probabilisticSharpe: 0.9231`, a 95% interval of `[-0.0332, 0.4624]`, and `periodsShortOfSignificance: 20`. Deterministic; identical on every call.
- **Expected error behaviour:** a body missing `trackRecord` for the inline source returns `400` with `error.code: "invalid_input"`, `retryable: false`, and `error.details.issues` naming the field path. A Nexus request with no key on a deployment with no demo key returns `401` with `error.code: "missing_credentials"` and a `remedy` naming the header. An unrecognised `Origin` returns `403`. Upstream failures map to `502`/`503`/`504` with `retryable: true`; a well-formed request whose data cannot support an answer returns `422`. The full code vocabulary is in `source/src/lib/errors.ts` and in the OpenAPI document.
- **The refusal path is the one worth checking.** A three-point curve returns `200` with `evidence.tier: "insufficient_evidence"` and `probabilisticSharpe: null` — no Sharpe ratio at all, because none would mean anything.

## Security and data handling

- **Data collected:** none is stored. An inline track record is analysed within the request and discarded; nothing is written to disk or to any database, and there is no database. There are no user accounts, no cookies, no analytics, and no telemetry.
- **Purpose and retention:** request-scoped computation only. Retention is zero. The only persistent state in the process is an in-memory cache of immutable point-in-time **market** data (no user data), bounded at 5,000 entries and lost on restart.
- **Third parties / outbound network calls:** exactly one — the OlaXBT Nexus MCP gateway at `https://nexus.olaxbt.xyz/api/mcp`, read-only, and only when a request selects `source: "olaxbt-nexus"`. Requests using the `inline` source make no outbound calls at all. `GET /api/v1/status` additionally probes the Nexus liveness endpoint. No user-supplied data is ever forwarded to a third party.
- **Credentials:** a caller's Nexus key is read from the `x-nexus-key` header, used for that request, and discarded. It is never persisted, never logged, and never echoed in a response. Where a key must be identified — rate-limit bucketing and cache partitioning — only a non-reversible fingerprint is used. Upstream error bodies are never forwarded verbatim, because they can contain account detail; they are mapped to our own error vocabulary.
- **Secrets:** no secrets are committed. The repository contains no `.env` file; `NEXUS_DEMO_KEY` and `REVIEW_COMMIT` are the only environment variables and both are optional, documented in the README.
- **Input hardening:** every request body is validated by schema before anything else runs, with bounds on every array (10,000 equity points, 20,000 trades, 20,000 resamples). `Origin` is validated on every entry point and unrecognised origins are refused with `403`. The service is read-only end to end: it has no write path, no filesystem access at request time, and no capability to move funds.
- **Known risks / restrictions:** the anonymous rate limit is per-instance and in-memory, so under horizontal scaling it limits per instance rather than globally — it exists to prevent accidental hammering, not abuse. A caller can supply a large equity curve within the documented bounds and consume CPU; request duration is capped by the platform. Analytical limits — the 45-date regime window, tercile edges depending on the sample, annualisation being approximate on irregular spacing, and the small-sample fragility of the non-normality correction — are listed under "Honest limits" in the README and surfaced in the API responses themselves rather than only in documentation.

## Support

- **Team / builder:** Solo builder.
- **Contact:** GitHub [@RaYYeR220](https://github.com/RaYYeR220) · X [@rayyer_220](https://x.com/rayyer_220)
- **License / rights:** MIT (`source/LICENSE`). Rights declaration in `RIGHTS.md`.
- **Discoverability:** the server is listed in the official MCP Registry as `io.github.RaYYeR220/regimen`, so any client that reads the registry can find and connect to it without configuration from us.
- **Operating commitment:** the deployment is a standard Next.js application on Vercel built straight from the public repository, so it has no cold-sleep behaviour and redeploys on every push. It will stay reachable through the announced review window. Adding a data source is an adapter against the existing interface rather than a change to the engine, which is the intended path for maintaining it.
