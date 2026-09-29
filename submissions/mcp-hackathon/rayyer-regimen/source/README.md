# Regimen

**A Sharpe ratio is an estimate. Regimen tells you whether it is a fact.**

Regimen takes a trading strategy's equity curve and answers two questions an aggregate
performance number cannot: **is the measured edge distinguishable from luck**, and **in
which market conditions does it actually hold?**

It is built for agents as much as for people. Everything is available over a REST API and
over MCP, and the most common answer it gives is that the evidence is too thin to support
the claim being made. That is the product, not a failure mode.

- **Live API** — https://regimen-nu.vercel.app
- **MCP endpoint** — `https://regimen-nu.vercel.app/mcp` (revision `2026-07-28`)
- **OpenAPI** — https://regimen-nu.vercel.app/api/v1/openapi.json
- **MCP Registry** — published as `io.github.RaYYeR220/regimen` ([listing](https://registry.modelcontextprotocol.io/v0/servers?search=regimen))
- **Verify it yourself** — [`verification/README.md`](./verification/README.md) · **Claims ledger** — [`CLAIMS.md`](./CLAIMS.md) · **Real vs simulated** — [`MOCKS.md`](./MOCKS.md) · **Scorecard** — [`EVAL.md`](./EVAL.md)

---

## The problem

A strategy publishes a Sharpe ratio of 2.4 over six weeks and a 58% win rate over 40
trades. Both numbers are real. Neither is evidence.

A Sharpe ratio computed from a short, skewed, fat-tailed sample carries an error bar wide
enough to swallow the claim. Forty trades cannot distinguish a 58% edge from a coin. And
once a strategy has been re-tuned twenty times, the best configuration looks good for the
same reason the tallest of twenty random people is tall.

This is not a niche statistical objection — it is the single most common way capital is
lost to a backtest. The mathematics for handling it has existed since 2012 and is almost
never applied, because it requires more than dividing a mean by a standard deviation.

Here is real output from the live service, on a curve with an **annualised Sharpe of 3.72**:

```
verdict      weak
confidence   92.3% that the true Sharpe exceeds 0
95% interval [-0.033, +0.462]        zero is still inside
track record 60 periods; 78 needed for significance at 95%
```

A dashboard would have printed `3.72` and stopped.

## What it does

**1. Significance.** The Probabilistic Sharpe Ratio — the probability the *true* Sharpe
exceeds a benchmark given the sample's length, skewness and kurtosis. The Minimum Track
Record Length — how many periods would be needed before the claim could be made at all.
The Deflated Sharpe Ratio — the same statement corrected for how many configurations were
tried first. A stationary-bootstrap confidence interval that preserves serial dependence.

**2. Regime attribution.** Each period's return is joined to the market conditions that
held on that UTC date — volatility, funding, open interest, positioning, sentiment, trend
state — read point-in-time, so nothing in a bucket could only have been known afterwards.
Every factor carries a **permutation test**: the observed dispersion of performance across
buckets is compared against the dispersion produced by randomly reshuffling the regime
labels, because slicing a return series eight ways guarantees a flattering subset. Without
that p-value a regime map is a data-mining machine.

**3. Self-attack.** Every analysis can be run against controls whose answer is known in
advance: the strategy's own returns with the mean removed (true Sharpe exactly zero, so a
correct engine must grade it near 50%), and a simulated population of edgeless strategies
matched for length and volatility, so the real result can be placed as a percentile against
pure luck. The result is published, including when a control fails.

**4. Divergence check.** Where a source publishes its own figures, Regimen recomputes them
from the equity curve and reports the difference. Differing conventions explain most gaps,
but a user quoting a dashboard deserves to know when the curve underneath says otherwise.

## Try it, with no credentials

```bash
curl -s https://regimen-nu.vercel.app/api/v1/evaluate \
  -H 'content-type: application/json' \
  -d '{
    "selector": {
      "source": "inline",
      "trackRecord": {
        "label": "demo",
        "equity": [
          {"t": "2026-06-01", "equity": 10000}, {"t": "2026-06-02", "equity": 10180},
          {"t": "2026-06-03", "equity": 10090}, {"t": "2026-06-04", "equity": 10310},
          {"t": "2026-06-05", "equity": 10240}, {"t": "2026-06-06", "equity": 10450}
        ]
      }
    }
  }'
```

That curve is deliberately too short, and Regimen says so rather than producing a number.
[`verification/README.md`](./verification/README.md) has a full-length example that
produces a graded verdict, plus the health and deployment-proof checks.

## Two surfaces, one engine

### REST

| Method | Path | What it answers |
|---|---|---|
| `POST` | `/api/v1/evaluate` | Is this track record distinguishable from luck? |
| `POST` | `/api/v1/regime-map` | Which market conditions is the edge concentrated in? |
| `POST` | `/api/v1/self-attack` | Why should I believe the verdict? |
| `GET` | `/api/v1/status` | Upstream reachability, cache occupancy, demo-key availability. |
| `GET` | `/api/v1/openapi.json` | The machine-readable contract. |
| `GET` | `/api/health` | Liveness and the exact build commit. |

Every response is `{ data, meta }` or `{ error, meta }`, where `meta` carries a request id,
the build commit, and which credential mode served the request. Errors carry a stable
machine-readable `code`, a `retryable` flag, and a `remedy` written to be actionable by an
agent rather than a human reading a stack trace.

### MCP

Connect any MCP client to `https://regimen-nu.vercel.app/mcp` over Streamable HTTP. No
authentication is needed for the `inline` source. For a client configured by file:

```json
{ "mcpServers": { "regimen": { "url": "https://regimen-nu.vercel.app/mcp" } } }
```

To inspect it interactively: `npx @modelcontextprotocol/inspector` and point it at the
same URL.

**Tools** — `regimen_evaluate_track_record`, `regimen_regime_map`, `regimen_self_attack`,
`regimen_describe_factors`. Each advertises an `outputSchema` and returns validated
`structuredContent`; each is annotated `readOnlyHint` because nothing here writes, trades
or signs; each takes a `detail` switch so an agent can ask for the verdict and its reasons
rather than every bucket.

**Resources** — `regimen://methodology` (the statistics, in full), `regimen://evidence-tiers`
(the exact grading thresholds), and the template `regimen://factor/{key}`, whose `key`
argument supports `completion/complete`.

**Prompt** — `validate_strategy`, the full review in the right order, with instructions not
to lead with the annualised Sharpe.

## Architecture

```
                    REST  /api/v1/*            MCP  /mcp
                          │                        │
                          └────────────┬───────────┘
                                       │
                            engine/  significance · regime · self-attack
                                       │
                            stats/   PSR · DSR · MinTRL · bootstrap ·
                                     conditional attribution · Wilson
                                       │
                            sources/ ── adapter interface ──┐
                                       │                     │
                              olaxbt-nexus              inline
                          (18 tools, point-in-time)  (bring your own curve)
```

The engine is written against a domain model — a track record, a regime series — and never
against a vendor's response shape. A data source is a thin adapter that produces those two
things. That is why the same analysis serves an OlaXBT Nexus strategy and a curve pasted in
from a spreadsheet, and why adding a venue is an adapter rather than a rewrite.

**OlaXBT Nexus is the live data source.** The adapter reads the strategy's equity curve,
trades and published metrics, and reads eight market-condition factors per date with an
explicit `as_of`, which is what makes the regime attribution free of lookahead. Rate
limiting and caching live in the client, not at call sites: a Builder-tier key allows 80
requests a minute and a regime map wants hundreds of point-in-time reads, so calls are paced
under a token bucket and every immutable past-dated read is cached.

## Testing

```bash
pnpm test          # the full suite
pnpm typecheck     # strict, with noUncheckedIndexedAccess
pnpm eval          # the graded evaluation; writes EVAL.md
```

The statistics core carries **370 tests**. Known-answer cases for PSR, MinTRL, the Deflated
Sharpe Ratio, skewness, kurtosis, Wilson intervals and drawdown were generated independently
of this implementation and carry their arithmetic in a comment. A negative-control test
across 20 seeds confirms a zero-mean series clears 95% confidence on 2 of 20 runs — the
nominal size — while the matching positive-mean series clears it on 20 of 20.

### What the evaluation found

`EVAL.md` is a pre-registered graded evaluation: 82 synthetic strategies with known ground
truth, scored on false-positive rate, power, correct refusals on degenerate input,
calibration, and regime detection. The suite and its targets were fixed before the engine
was ever run against them.

**It currently fails three of its six targets, and the failures are published rather than
tuned away.** They are worth reading, because they are the honest limits of the method:

- **False positives 5.6% (2/36), target ≤5%.** Both failures are the same mechanism: a
  negatively-skewed return distribution on a short window whose crash component simply has
  not arrived yet. The non-normality correction is driven by the *sample* third and fourth
  moments, and at 40–60 observations those carry almost no information — so the exact
  pattern the correction exists to catch ("sells volatility, hasn't blown up yet") is the
  one it walks into. The engine now says so explicitly in its own reasoning whenever a
  sample is too short for those moments to mean anything. Note that 2 of 36 is also within
  Monte Carlo noise of the nominal 5%; the mechanism is the finding, not the overshoot.
- **Restraint 66.7% (10/15), target ≥90%.** In five cases a genuine but unprovable edge was
  graded as proven, because luck pushed the observed Sharpe far above the true one. The
  engine is directionally right in all five and still granting more confidence than the
  sample size supports.
- **Regime detection 25% (1/4) at p ≤ 0.05, target ≥75%.** The evaluation caught a real
  design flaw here: the permutation test originally ran on the best-minus-worst Sharpe
  spread, which sees only two buckets and inflates with the number of buckets. On a planted
  effect it could not separate signal from the null at all — planted spread 0.493 against a
  null control's 0.491. It was replaced with an observation-weighted between-bucket
  variance, which moved the planted cases' p-values from 0.022/0.073/0.092/0.229 to
  0.010/0.054/0.069/0.275 while the unplanted controls stayed quiet (0.18–0.91). That is a
  material improvement and still short of the target, so the target stands as missed.

Regime false positives are 0/4 and degenerate inputs are refused 8/8.

### MCP conformance

`npx @modelcontextprotocol/conformance@alpha server --url <url>`

Against a local build: **36 checks pass, 23 fail.** Passing: protocol negotiation, `ping`,
`tools/list`, `resources/list`, `prompts/list`, and DNS-rebinding protection. **Every failure
is a scenario that exercises the suite's own reference-server fixtures** — named test tools,
sampling, logging, image and audio content, resource subscriptions — none of which Regimen
implements. The raw counts are printed here rather than summarised as a pass, because a
conformance claim that hides its denominator is worth nothing.

Note that the DNS-rebinding scenario reports failure against any non-localhost URL by
construction (it states so in its own description), so it is meaningful only when run
against a local build.

## Running locally

```bash
pnpm install
pnpm dev        # http://localhost:3000
```

No credentials are needed for the inline source. To analyse an OlaXBT Nexus strategy,
supply a key per request in the `x-nexus-key` header, or set one in the environment.

| Variable | Required | What it does |
|---|---|---|
| `NEXUS_DEMO_KEY` | no | An OlaXBT Nexus API key used when a caller supplies none, so a reviewer can exercise the Nexus-backed endpoints without an account. Responses report `meta.mode: "demo"` when it is in use. |
| `REVIEW_COMMIT` | no | Overrides the commit reported by `/api/health`. Only needed when self-hosting outside a git-aware build; otherwise the platform's build metadata is used, which is what keeps the reported commit honest. |

Keys are read per request, never persisted, and never logged. Where a key must be
identified — for rate limiting and cache partitioning — only a non-reversible fingerprint
is used.

## Honest limits

- **A regime map reads at most 45 dates per request.** Each date costs five point-in-time
  reads and the upstream allows 80 a minute. Past dates are immutable and cached, so
  repeating the call widens coverage; a single request will not.
- **Upstream point-in-time coverage ends before the present.** Conditions for very recent
  dates may be unavailable, and those periods are reported as unmatched rather than filled in.
- **The Deflated Sharpe Ratio only appears when trial Sharpes are supplied.** Regimen cannot
  know how many configurations you tried, and it will not guess — it says the ratio was not
  computed and why.
- **Tercile bucket edges depend on the sample.** Factors with a conventional scale use edges
  fixed in advance; the rest are split into terciles of their own observed range, which is
  disclosed per factor.
- **Annualised figures are approximations when equity points are unevenly spaced.** Regimen
  infers the period from the median spacing, flags irregularity, and grades on per-period
  figures rather than annualised ones.
- **The evaluation is modelled, not live.** It measures the engine against synthetic
  strategies with known truth. It does not demonstrate profitability of anything.

## Not in scope

Regimen does not trade, hold funds, custody keys, or sign anything. It does not inspect
smart contracts, score wallets or transactions, detect scams, or perform security,
audit or compliance analysis of any kind. It reads a track record and reports what the
evidence supports.

## License

MIT — see [`LICENSE`](./LICENSE).
