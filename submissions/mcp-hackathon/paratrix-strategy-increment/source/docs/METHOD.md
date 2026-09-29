# Method and data semantics

Method version: `fixed-initial-80-20/v1`. This document is the canonical method definition. Fields are specified in [IMPLEMENTATION-CONTRACT.md](IMPLEMENTATION-CONTRACT.md); recorded behavior checks are in [VALIDATION.md](VALIDATION.md).

## Input requirements

A and B must provide complete simulated mark-to-market equity curves with the same currency, valuation frequency, and time semantics. At minimum, record:

| Field group | Requirement |
| --- | --- |
| Source | `recorded_local_aimm`, `recorded_nexus`, `inline_simulation`, or `synthetic`, with the available source declarations |
| Identity | Strategy identifier, backtest/run identifier, and available configuration and engine version |
| Initial valuation | Explicit initial equity, interval boundary, and valuation instant; the first post-return observation must not stand in for starting capital |
| Time | Calendar, timezone, frequency, and whether timestamps are bar labels or actual valuation instants |
| Series | Equity on a complete time grid, with explicit handling of ordering, duplicates, and missing observations |
| Capital and costs | No external deposits or withdrawals; explicit, compatible cost models; unknown costs cannot be assumed complete |

Missing dates are not filled with zeros. Sampled curves are not interpolated. Points are not silently discarded, and the interval is not silently shortened to an intersection. An explicitly selected shorter interval is saved in the experiment configuration. Bar-open labels cannot be paired directly with closing valuations; adapters must record and convert verified time semantics.

Snapshot `created_at` records when this service saved an input. It is not the upstream retrieval time. Optional upstream context belongs in the supported provenance fields, such as `description`, `data_version`, `engine_version`, and `reference`; the curve schema has no separate retrieval-time field.

Non-finite values and non-positive equity that the model cannot interpret are rejected. Small samples may be used for clearly labeled descriptive demonstrations, without a statistical-validity claim. Source and no-cash-flow declarations are user or system records, not independent certification.

## Fixed initial allocation model

For the explicit initial valuation instant `t0` of an experiment interval:

```text
NAV_A(t) = E_A(t) / E_A(t0)
NAV_B(t) = E_B(t) / E_B(t0)
V_A(t)   = NAV_A(t)
V_AB(t)  = 0.8 * NAV_A(t) + 0.2 * NAV_B(t)
V_AC(t)  = 0.8 * NAV_A(t) + 0.2
```

Cash return is zero, and every path starts at 1. Initial capital is allocated 80/20; there is no portfolio-level rebalancing, so the effective portfolio weights drift as A and B change value. Weighting each day's returns 80/20 would represent a different model and cannot be described as no rebalancing. Each reported interval starts with a fresh allocation at its explicit initial point; drifted weights from a preceding design interval are not silently carried into a fixed evaluation.

This is a study of independent equity units combined into a portfolio. It does not simulate execution in a shared account, position netting, margin, liquidation, minimum order sizes, fixed fees, or nonlinear effects of capital size on signals. A claim about actual execution with an 80/20 capital allocation requires backtests at the corresponding capital levels.

## Metrics

```text
R(V)    = V(t_end) / V(t0) - 1
Peak(t) = max(V(s), t0 <= s <= t)
DD(t)   = 1 - V(t) / Peak(t)
MDD(V)  = max(DD(t))
```

Maximum drawdown is shown as a positive loss magnitude. Daily returns use complete adjacent valuations. The application reports daily-return sample standard deviation without silently applying an equity-market convention of 252 annual trading days. Correlation, joint-loss days, and dates that illustrate differences are explanatory diagnostics; they do not determine whether criteria are met. Undefined correlation caused by zero volatility is unavailable, not zero.

Drawdown is valid only at the input frequency: even complete daily data cannot establish intraday maximum drawdown. Metrics retain costs already included in source equity and do not deduct them again. No portfolio-level rebalancing does not mean that trading within a strategy is free.

## Four research criteria

Return and drawdown differences are expressed in percentage points. Let the user thresholds be `d_min`, `r_loss_max`, `r_cash_min`, and `d_cash_max`:

| Criterion | Passing condition |
| --- | --- |
| Drawdown improvement relative to A | `100 * (MDD(A) - MDD(AB)) >= d_min` |
| Return sacrifice relative to A | `100 * (R(A) - R(AB)) <= r_loss_max` |
| Additional return above the cash control | `100 * (R(AB) - R(AC)) >= r_cash_min` |
| Additional drawdown above the cash control | `100 * (MDD(AB) - MDD(AC)) <= d_cash_max` |

Thresholds express a researcher's preferences. They are neither statistical significance tests nor universal investment standards. Teaching defaults must be labeled as examples. With all four criteria supplied, every condition must pass. With all four absent, the result reports facts only. Partially supplied criteria are rejected rather than completed with implicit defaults.

Calculations preserve decimal input precision, and metrics are serialized under the precision rules below. Criteria are evaluated before display rounding.

## Output states

- `not_evaluable`: required inputs are missing or incompatible; reasons identify the affected field or date.
- `comparison_only`: inputs are comparable and no criteria were supplied; the output reports facts only.
- `criteria_met`: every supplied criterion is met, with individual evidence.
- `criteria_not_met`: inputs are comparable but at least one criterion is not met; the output identifies the tradeoffs.

Malformed input, service failure, and storage failure are technical errors and cannot be reported as a failed research criterion. An unevaluable experiment request returns HTTP 422 with a `not_evaluable` error and saves no experiment. The three successful computation states are stored in `result.status`.

## Evaluation declarations and reproduction

Ordinary imports default to historical exploration. The application records when the candidate and criteria were saved, the evaluation interval, and declarations about previously seen data. It cannot establish that data was unseen on the user's behalf. Changing a candidate, dataset, or threshold creates a new experiment. Changes to the method or adapter version also require new results.

Identical snapshots, configuration, and method versions must produce the same numerical values and state. Content hashes establish file consistency, not market authenticity, author identity, or economic validity. Evidence packages must contain no credentials. A source that cannot be redistributed cannot be presented as enabling complete public reproduction.

## Required properties

When B equals A, AB must equal A. When B is constant cash, AB must equal AC. Low correlation combined with losses does not automatically pass. Lower drawdown with return sacrifice above the threshold must fail. Interpolation cannot hide missing observations or an incompatible valuation clock. Concrete cases are listed in [ACCEPTANCE.md](ACCEPTANCE.md).

## Numerical precision

Each calculation uses an independent 50-digit Decimal context with `ROUND_HALF_EVEN`; it does not inherit the caller's context. Inputs allow at most 40 significant digits and a nonzero adjusted exponent from -30 to 30. Criteria range from 0 to 10,000 percentage points. Equity and metrics are serialized as decimal strings; auxiliary correlation is a finite float or `null`. HTTP parsing preserves decimal JSON number text as strings. Browser uploads forward the original text instead of parsing and reserializing through JavaScript floating point. Formatting affects display only, never the outcome. Explicit unknown-cost markers are rejected; other cost-model strings remain source declarations, not an independent audit.

`coverage.observations` includes the initial valuation point. The daily-return count is one lower. With only one daily return, sample volatility and correlation are `null`. Facts-only results still include all four differences in `comparison_facts`, but make no criteria-met claim.
