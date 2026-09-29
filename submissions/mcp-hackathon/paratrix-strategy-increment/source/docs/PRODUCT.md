# Product and user value

Strategy Increment helps researchers assess what changes when a candidate strategy joins an existing baseline. Import two simulated backtest equity curves, compare the baseline, an initial 80/20 strategy portfolio, and the equivalent cash control, inspect return and drawdown differences, and save an experiment that can be reproduced offline.

See the [method](METHOD.md) for calculation semantics, the [implementation contract](IMPLEMENTATION-CONTRACT.md) for inputs and endpoints, and [validation records](VALIDATION.md) for checks that have been performed.

## Problem

A researcher has baseline strategy A and a backtest for candidate B. The concrete question is: "What improves if I add B instead of continuing with A? How would the result compare with keeping the same allocation in cash?"

Three controls reveal the candidate's contribution, return sacrifice, and risk changes together. A researcher can compare facts only, or specify four criteria before running the experiment and inspect the actual differences and evidence behind each outcome.

The product accepts complete simulated equity JSON and provides examples that require no credentials. The research workflow needs no live account data or trading permissions.

## Users and value

| User | Need | Capability |
| --- | --- | --- |
| Strategy researcher | Understand the return/drawdown tradeoff when adding a candidate | Inspect the baseline, candidate portfolio, and cash control in one experiment |
| Consumer of backtest results | Determine whether two results are suitable for comparison | Check dates, currency, valuation frequency, starting capital, and cost semantics |
| Agent performing research | Obtain explicit conditions and referenceable results | Read individual facts, states, and provenance through an API |
| Research collaborator | Review another person's conclusion and retain its basis | Download inputs, rules, versions, and results for offline reproduction |

## Experiment model

- Select one baseline A and one candidate B, using complete simulated equity in the same currency and daily valuation calendar.
- The three controls are fixed: 100% A, initially 80% A + 20% B, and initially 80% A + 20% cash.
- Independent equity units are combined at their initial allocations without subsequent rebalancing. Cash return is assumed to be zero.
- Users can explicitly select the experiment interval. Each interval is normalized from its own initial valuation point.
- Five examples cover local AIMM weight variants, a copy of A, constant cash, a missing day, and a return/drawdown tradeoff.

The 80/20 allocation provides a consistent research comparison. It does not simulate shared-account margin, netting, or execution costs. Full assumptions and scope are in the [method](METHOD.md).

## Capabilities and complete workflow

| Capability | User action | Result |
| --- | --- | --- |
| Choose or import | Load an example or upload two simulated equity JSON files | Inspect provenance, backtest identifiers, and valuation coverage |
| Check comparability | Check dates, frequency, currency, costs, and cash-flow conditions | Locate data problems at a specific field or timestamp |
| Fix research rules | Confirm the interval and four criteria, or select facts-only mode | Save the conditions and inputs as an independent experiment |
| Compare three scenarios | Inspect total return, maximum drawdown, and complete paths | Compare the baseline and equivalent cash allocation together |
| Explain tradeoffs | Inspect four differences and whether each threshold is met | Understand the outcome through concrete metrics |
| History and derivation | Restore an experiment, then change its conditions | Preserve the old result and the parent/child relationship |
| Export and reproduce | Download a package and verify it with the offline CLI | Recompute inputs, metrics, and the outcome |
| API invocation | Perform the same workflow through an agent or research tool | Use the same calculation engine as the workbench and CLI |

The Chinese-language workbench follows "choose results → confirm interval and rules → run experiment → inspect and reproduce." Reports show the conclusion and three scenarios first, followed by criteria, equity and drawdown paths, explanatory dates, and provenance. Technical versions and hashes are in the evidence area. Public documentation and API messages are in English.

The interface distinguishes computation in progress, insufficient data, service failure, and completed computation. After an input changes, the previous report is marked as the last saved result. Running again creates a new record.

## Interpreting the result

The four criteria constrain drawdown improvement relative to A, return sacrifice relative to A, additional return above cash, and additional drawdown above cash. When all four pass, the result states that the predefined research criteria are met. If at least one fails, the report identifies the corresponding tradeoff.

With no criteria, the output reports facts only. With an incomplete set, the user must complete it or switch to facts-only mode. Correlation and joint-loss days provide explanation and do not participate in the four-condition decision.

The conclusion describes the selected historical interval under fixed experiment rules. Insufficient data blocks calculation. Historical success against criteria does not imply future performance.

## Research records and scope

Ordinary imports default to historical exploration. Records include whether the user has seen the data and when the candidate, criteria, and interval were saved. Experiments repeatedly modified over the same interval retain an exploration label. A declared holdout is a user declaration; the system cannot certify whether the user has seen the data elsewhere.

The product focuses on comparing simulated results, recording experiments, and independent review. Automatic strategy generation, dynamic weighting, bulk strategy search, statistical significance testing, and live execution are outside this version. Cloudflare Workers supports examples and JSON imports. External Nexus imports are disabled. See [deployment](DEPLOYMENT.md), [source adapters](../app/adapters/README.md), and the [input contract](IMPLEMENTATION-CONTRACT.md) for configuration and complete-curve requirements.
