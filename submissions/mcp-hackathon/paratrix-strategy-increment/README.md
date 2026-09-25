# Strategy Increment

**What changes in return and drawdown when you add a candidate strategy?**

Strategy Increment turns two simulated backtest equity curves into a reproducible comparison. Researchers can compare the baseline, a portfolio that adds the candidate, and a portfolio that holds the same allocation in cash, then assess the candidate against their research criteria.

Maintained by [karpak-labs](https://github.com/karpak-labs) · [MIT](LICENSE) · [Support](https://github.com/karpak-labs/strategy-increment/issues)

[Research workbench](https://strategy-increment.raspy-boat-dbb0.workers.dev/) · [API documentation](https://strategy-increment.raspy-boat-dbb0.workers.dev/docs) · [Health and source version](https://strategy-increment.raspy-boat-dbb0.workers.dev/health)

## Capabilities

- **Three controls:** 100% A, initially 80% A + 20% B, and initially 80% A + 20% cash.
- **Explicit tradeoffs:** compare drawdown improvement, return sacrifice, return above the cash control, and additional drawdown above that control. Report facts alone or evaluate four criteria.
- **Input checks:** identify incompatible dates, valuation clocks, currencies, costs, and incomplete data at the affected fields.
- **Research records:** save inputs, intervals, rules, and results. Changed conditions create a new experiment with a link to its parent.
- **Independent reproduction:** export a complete evidence JSON file and verify it offline with the Python CLI.
- **Workbench and API:** researchers use the Chinese-language workbench; agents perform the same task through the HTTP API. API messages and review documentation are in English.

## Quick start

Install Python 3.13 or 3.14, Node.js 22 or later, and [uv](https://docs.astral.sh/uv/) 0.12.3 or later. From the repository root:

```bash
cd source
python3 scripts/build_worker.py
cd runtime/worker-bundle
npm ci
uv run --locked pywrangler dev --local
```

Open the [research workbench](http://127.0.0.1:8787), choose an example or import simulated equity JSON for A and B, select the interval and criteria, and run the experiment. The five built-in examples need no external credentials. See [running the application and using the API](source/README.md) for the input format and endpoints.

After downloading an evidence file, run this from `source/`:

```bash
python3 -m app.reproduce /path/to/evidence.json
```

Cloudflare Workers uses SQLite-backed Durable Objects for persistent session records. See the [deployment guide](source/docs/DEPLOYMENT.md) for the build, configuration, and release procedure. Local development uses Wrangler with the same Worker entrypoint, asset binding and Durable Object storage as deployment. After source changes, stop Wrangler, rebuild, and restart it; the matching code/assets bundle is refreshed while local session data is preserved.

## A hand-checkable example

A has equity `100 → 80 → 110`; B has `100 → 120 → 105`. With fixed initial allocations:

| Scenario | Interval return | Maximum drawdown |
| --- | --- | --- |
| 100% A | 10% | 20% |
| 80% A + 20% B | 9% | 12% |
| 80% A + 20% cash | 8% | 16% |

Adding B improves drawdown by 8 percentage points and sacrifices 1 percentage point of return relative to A. Relative to the cash control, it adds 1 percentage point of return and reduces drawdown by 4 percentage points. These four differences are the values assessed by the research criteria.

## Method and data

Inputs are complete daily simulated equity curves. The model uses fixed initial allocations, no portfolio rebalancing, and zero cash return over the selected historical interval. Daily maximum drawdown does not include intraday extremes. Results describe strategy research and do not predict future returns.

Recorded local AIMM runs, constructed teaching examples, and user imports retain their source labels. The Worker supports examples and simulation JSON imports. The service makes no external Nexus calls; see [source adapters](source/app/adapters/README.md).

## Documentation

| Document | Contents |
| --- | --- |
| [Product](source/docs/PRODUCT.md) | User problem, capabilities, and complete research workflow |
| [Method](source/docs/METHOD.md) | Model, metrics, numerical precision, and research criteria |
| [API contract](source/docs/IMPLEMENTATION-CONTRACT.md) | Inputs, outputs, sessions, and errors |
| [Architecture](source/docs/ARCHITECTURE.md) | Data flow, storage, and reproduction |
| [Validation](source/docs/VALIDATION.md) | Behavior coverage and recorded verification results |
| [Deployment](source/docs/DEPLOYMENT.md) | Cloudflare Workers, Wrangler development, configuration, and persistence |
| [Reviewer walkthrough](verification/README.md) | Health checks, business workflow, and offline reproduction |
| [Rights and provenance](RIGHTS.md) | First-party license, dependencies, and sample sources |
| [Submission](SUBMISSION.md) | Product value, deliverables, and review path |

See [RELEASE.md](source/docs/RELEASE.md) for release operations.
