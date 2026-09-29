# Regimen evaluation scorecard

Regimen claims to tell you whether a track record is distinguishable from luck. This file is the check on that claim.

The engine was run against 82 synthetic strategies whose truth is known in advance: some have a real edge, most have none, a few are not strategies at all. The suite and the targets below were fixed before the engine was ever run against them, and are not adjusted afterwards. A missed target is a finding, not a prompt to move the target.

Reproduce this file exactly: `pnpm eval`

**Result: FAILED**

Targets missed:

- False positive rate: measured 0.0556 (2/36), target <= 0.05.
- Restraint: measured 0.6667 (10/15), target >= 0.90.
- Regime detection rate: measured 0.2500 (1/4), target >= 0.75.

## Targets and measured results

| Measure | What it counts | Pre-registered target | Measured | Verdict |
| --- | --- | --- | --- | --- |
| False positive rate | No-edge records graded supported/strong | <= 0.05 | 5.6% (2/36) | MISSED |
| Power | Provable real edges graded supported/strong | >= 0.80 | 80.0% (12/15) | met |
| Correct refusals | Degenerate inputs returning insufficient_evidence | 1.00 | 100.0% (8/8) | met |
| Restraint | Unprovable real edges the engine declined to claim | >= 0.90 | 66.7% (10/15) | MISSED |
| Regime detection | Planted regime effects found at p <= 0.05 | >= 0.75 | 25.0% (1/4) | MISSED |
| Regime false positives | Unplanted factors claimed at p <= 0.05 | <= 0.05 | 0.0% (0/4) | met |

"Claimed" means the engine returned supported or strong. `weak` is not counted as a claim: the engine describes it as "positive but not convincing", and hedging is the behaviour we want from it.

Restraint is the measure that is easy to skip and hardest to fake. Those 15 cases carry a genuine edge on a sample shorter than the analytic minimum track record length for that edge at 95% confidence. The evidence is real and unprovable at the same time, and declining to claim it is the right answer.

## Calibration

When the engine reports a Probabilistic Sharpe Ratio of 0.95, roughly 95% of the records it says that about should really have an edge. This table checks that across the suite.

| Reported confidence (PSR) | Cases | Truly had an edge | Observed frequency |
| --- | --- | --- | --- |
| < 0.50 | 18 | 2 | 11.1% |
| 0.50 - 0.90 | 28 | 11 | 39.3% |
| 0.90 - 0.95 | 5 | 3 | 60.0% |
| 0.95 - 0.99 | 8 | 7 | 87.5% |
| >= 0.99 | 15 | 13 | 86.7% |

Read this against the suite composition rather than as an absolute: the suite is deliberately loaded with edgeless records, so the base rate in the low bands is low by construction. What matters is that the observed frequency climbs with the reported confidence and gets close to it at the top.

## Regime detection

Each planted case hides its entire edge inside high-VIX periods. Each null case is built identically — same factor series, same bucket split — with no difference between the buckets. The permutation test should find the first group and stay quiet on the second.

- Planted effects found: 25.0% (1/4) at p <= 0.05
- Effects claimed where nothing was planted: 0.0% (0/4) at p <= 0.05

## Failing cases

Each line carries the sample skewness the engine measured next to the true skewness of the distribution the record was drawn from. On short windows those two numbers can be very far apart, and the Probabilistic Sharpe Ratio corrects for non-normality using the sample one.

- `no-edge/skewed/n40/b` — False positive: graded strong on a record with no edge. True Sharpe 0.000, observed 0.488 over 40 periods; sample skewness -0.29 against a true -1.96.
- `no-edge/skewed/n60/b` — False positive: graded strong on a record with no edge. True Sharpe 0.000, observed 0.383 over 60 periods; sample skewness -0.72 against a true -1.96.
- `edge/normal/sr10/n400` — Missed a provable edge: graded weak. True Sharpe 0.100, observed 0.079 over 400 periods; sample skewness -0.12 against a true 0.00.
- `edge/skewed/sr25/n120` — Missed a provable edge: graded indistinguishable_from_luck. True Sharpe 0.250, observed 0.141 over 120 periods; sample skewness -3.41 against a true -1.96.
- `edge/skewed/sr15/n250` — Missed a provable edge: graded indistinguishable_from_luck. True Sharpe 0.150, observed 0.067 over 250 periods; sample skewness -1.88 against a true -1.96.
- `short-edge/normal/sr30/n30` — Over-claimed: graded supported on a sample shorter than the required track record. True Sharpe 0.300, observed 0.386 over 30 periods; sample skewness 0.17 against a true 0.00.
- `short-edge/normal/sr10/n80` — Over-claimed: graded strong on a sample shorter than the required track record. True Sharpe 0.100, observed 0.323 over 80 periods; sample skewness 0.09 against a true 0.00.
- `short-edge/skewed/sr30/n30` — Over-claimed: graded strong on a sample shorter than the required track record. True Sharpe 0.300, observed 0.916 over 30 periods; sample skewness -1.24 against a true -1.96.
- `short-edge/skewed/sr25/n25` — Over-claimed: graded supported on a sample shorter than the required track record. True Sharpe 0.250, observed 0.470 over 25 periods; sample skewness -0.92 against a true -1.96.
- `short-edge/skewed/sr10/n80` — Over-claimed: graded supported on a sample shorter than the required track record. True Sharpe 0.100, observed 0.326 over 80 periods; sample skewness -1.94 against a true -1.96.
- `regime/planted/normal/n180` — Missed the planted regime effect (p = 0.0695). True Sharpe 0.172, observed 0.076 over 180 periods; sample skewness -0.27 against a true 0.00.
- `regime/planted/skewed/n180` — Missed the planted regime effect (p = 0.2749). True Sharpe 0.172, observed 0.112 over 180 periods; sample skewness -1.98 against a true -1.96.
- `regime/planted/fat/n300` — Missed the planted regime effect (p = 0.0540). True Sharpe 0.123, observed 0.069 over 300 periods; sample skewness 0.29 against a true 0.00.

## Suite composition

| Group | Cases | Pass rule |
| --- | --- | --- |
| no_edge | 36 | must not be graded supported/strong |
| edge_provable | 15 | should be graded supported/strong |
| edge_not_provable | 15 | must not be graded supported/strong |
| regime_planted | 4 | planted factor permutation p <= 0.05 |
| regime_null | 4 | planted factor permutation p > 0.05 |
| degenerate | 8 | must return insufficient_evidence |

## Settings

- Benchmark Sharpe: 0 (per period) — "is there any edge at all?"
- Bootstrap resamples: 2000, seed 1592594996
- Regime permutations: 2000, seed 12648430
- Moment matching: population — shapes are standardised by their population moments, so a no-edge sample can still look good by luck. That is what makes the false positive rate a measurement rather than an identity.

## Every case

| Case | Group | Expectation | Periods | True SR | Provable | Observed tier | PSR | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| no-edge/normal/n25/a | no_edge | must not be graded supported/strong | 25 | 0.000 | no | indistinguishable_from_luck | 0.1467 | pass |
| no-edge/normal/n25/b | no_edge | must not be graded supported/strong | 25 | 0.000 | no | indistinguishable_from_luck | 0.7256 | pass |
| no-edge/normal/n40/a | no_edge | must not be graded supported/strong | 40 | 0.000 | no | indistinguishable_from_luck | 0.1706 | pass |
| no-edge/normal/n40/b | no_edge | must not be graded supported/strong | 40 | 0.000 | no | indistinguishable_from_luck | 0.6819 | pass |
| no-edge/normal/n60/a | no_edge | must not be graded supported/strong | 60 | 0.000 | no | weak | 0.9434 | pass |
| no-edge/normal/n60/b | no_edge | must not be graded supported/strong | 60 | 0.000 | no | indistinguishable_from_luck | 0.3673 | pass |
| no-edge/normal/n120/a | no_edge | must not be graded supported/strong | 120 | 0.000 | no | indistinguishable_from_luck | 0.8279 | pass |
| no-edge/normal/n120/b | no_edge | must not be graded supported/strong | 120 | 0.000 | no | indistinguishable_from_luck | 0.7407 | pass |
| no-edge/normal/n250/a | no_edge | must not be graded supported/strong | 250 | 0.000 | no | indistinguishable_from_luck | 0.4140 | pass |
| no-edge/normal/n250/b | no_edge | must not be graded supported/strong | 250 | 0.000 | no | indistinguishable_from_luck | 0.6935 | pass |
| no-edge/normal/n500/a | no_edge | must not be graded supported/strong | 500 | 0.000 | no | indistinguishable_from_luck | 0.5763 | pass |
| no-edge/normal/n500/b | no_edge | must not be graded supported/strong | 500 | 0.000 | no | indistinguishable_from_luck | 0.0698 | pass |
| no-edge/skewed/n25/a | no_edge | must not be graded supported/strong | 25 | 0.000 | no | indistinguishable_from_luck | 0.7788 | pass |
| no-edge/skewed/n25/b | no_edge | must not be graded supported/strong | 25 | 0.000 | no | weak | 0.9326 | pass |
| no-edge/skewed/n40/a | no_edge | must not be graded supported/strong | 40 | 0.000 | no | indistinguishable_from_luck | 0.5359 | pass |
| no-edge/skewed/n40/b | no_edge | must not be graded supported/strong | 40 | 0.000 | no | strong | 0.9967 | FAIL |
| no-edge/skewed/n60/a | no_edge | must not be graded supported/strong | 60 | 0.000 | no | indistinguishable_from_luck | 0.6707 | pass |
| no-edge/skewed/n60/b | no_edge | must not be graded supported/strong | 60 | 0.000 | no | strong | 0.9940 | FAIL |
| no-edge/skewed/n120/a | no_edge | must not be graded supported/strong | 120 | 0.000 | no | indistinguishable_from_luck | 0.1829 | pass |
| no-edge/skewed/n120/b | no_edge | must not be graded supported/strong | 120 | 0.000 | no | indistinguishable_from_luck | 0.0871 | pass |
| no-edge/skewed/n250/a | no_edge | must not be graded supported/strong | 250 | 0.000 | no | indistinguishable_from_luck | 0.6290 | pass |
| no-edge/skewed/n250/b | no_edge | must not be graded supported/strong | 250 | 0.000 | no | indistinguishable_from_luck | 0.7550 | pass |
| no-edge/skewed/n500/a | no_edge | must not be graded supported/strong | 500 | 0.000 | no | indistinguishable_from_luck | 0.5434 | pass |
| no-edge/skewed/n500/b | no_edge | must not be graded supported/strong | 500 | 0.000 | no | indistinguishable_from_luck | 0.1496 | pass |
| no-edge/fat/n25/a | no_edge | must not be graded supported/strong | 25 | 0.000 | no | indistinguishable_from_luck | 0.3381 | pass |
| no-edge/fat/n25/b | no_edge | must not be graded supported/strong | 25 | 0.000 | no | indistinguishable_from_luck | 0.4525 | pass |
| no-edge/fat/n40/a | no_edge | must not be graded supported/strong | 40 | 0.000 | no | indistinguishable_from_luck | 0.1121 | pass |
| no-edge/fat/n40/b | no_edge | must not be graded supported/strong | 40 | 0.000 | no | indistinguishable_from_luck | 0.1124 | pass |
| no-edge/fat/n60/a | no_edge | must not be graded supported/strong | 60 | 0.000 | no | indistinguishable_from_luck | 0.3405 | pass |
| no-edge/fat/n60/b | no_edge | must not be graded supported/strong | 60 | 0.000 | no | indistinguishable_from_luck | 0.7721 | pass |
| no-edge/fat/n120/a | no_edge | must not be graded supported/strong | 120 | 0.000 | no | indistinguishable_from_luck | 0.3430 | pass |
| no-edge/fat/n120/b | no_edge | must not be graded supported/strong | 120 | 0.000 | no | indistinguishable_from_luck | 0.5612 | pass |
| no-edge/fat/n250/a | no_edge | must not be graded supported/strong | 250 | 0.000 | no | weak | 0.9614 | pass |
| no-edge/fat/n250/b | no_edge | must not be graded supported/strong | 250 | 0.000 | no | indistinguishable_from_luck | 0.7454 | pass |
| no-edge/fat/n500/a | no_edge | must not be graded supported/strong | 500 | 0.000 | no | indistinguishable_from_luck | 0.1763 | pass |
| no-edge/fat/n500/b | no_edge | must not be graded supported/strong | 500 | 0.000 | no | indistinguishable_from_luck | 0.7328 | pass |
| edge/normal/sr40/n60 | edge_provable | should be graded supported/strong | 60 | 0.400 | yes | strong | 0.9995 | pass |
| edge/normal/sr30/n90 | edge_provable | should be graded supported/strong | 90 | 0.300 | yes | strong | 1.0000 | pass |
| edge/normal/sr25/n120 | edge_provable | should be graded supported/strong | 120 | 0.250 | yes | strong | 0.9958 | pass |
| edge/normal/sr15/n250 | edge_provable | should be graded supported/strong | 250 | 0.150 | yes | strong | 0.9938 | pass |
| edge/normal/sr10/n400 | edge_provable | should be graded supported/strong | 400 | 0.100 | yes | weak | 0.9419 | FAIL |
| edge/skewed/sr40/n60 | edge_provable | should be graded supported/strong | 60 | 0.400 | yes | strong | 1.0000 | pass |
| edge/skewed/sr30/n90 | edge_provable | should be graded supported/strong | 90 | 0.300 | yes | strong | 0.9964 | pass |
| edge/skewed/sr25/n120 | edge_provable | should be graded supported/strong | 120 | 0.250 | yes | indistinguishable_from_luck | 0.8910 | FAIL |
| edge/skewed/sr15/n250 | edge_provable | should be graded supported/strong | 250 | 0.150 | yes | indistinguishable_from_luck | 0.8382 | FAIL |
| edge/skewed/sr10/n400 | edge_provable | should be graded supported/strong | 400 | 0.100 | yes | strong | 0.9984 | pass |
| edge/fat/sr40/n60 | edge_provable | should be graded supported/strong | 60 | 0.400 | yes | supported | 0.9895 | pass |
| edge/fat/sr30/n90 | edge_provable | should be graded supported/strong | 90 | 0.300 | yes | strong | 1.0000 | pass |
| edge/fat/sr25/n120 | edge_provable | should be graded supported/strong | 120 | 0.250 | yes | supported | 0.9878 | pass |
| edge/fat/sr15/n250 | edge_provable | should be graded supported/strong | 250 | 0.150 | yes | strong | 0.9938 | pass |
| edge/fat/sr10/n400 | edge_provable | should be graded supported/strong | 400 | 0.100 | yes | strong | 0.9997 | pass |
| short-edge/normal/sr30/n30 | edge_not_provable | must not be graded supported/strong | 30 | 0.300 | no | supported | 0.9818 | FAIL |
| short-edge/normal/sr25/n25 | edge_not_provable | must not be graded supported/strong | 25 | 0.250 | no | indistinguishable_from_luck | 0.7196 | pass |
| short-edge/normal/sr15/n45 | edge_not_provable | must not be graded supported/strong | 45 | 0.150 | no | indistinguishable_from_luck | 0.8111 | pass |
| short-edge/normal/sr10/n80 | edge_not_provable | must not be graded supported/strong | 80 | 0.100 | no | strong | 0.9976 | FAIL |
| short-edge/normal/sr08/n150 | edge_not_provable | must not be graded supported/strong | 150 | 0.080 | no | indistinguishable_from_luck | 0.7955 | pass |
| short-edge/skewed/sr30/n30 | edge_not_provable | must not be graded supported/strong | 30 | 0.300 | no | strong | 0.9982 | FAIL |
| short-edge/skewed/sr25/n25 | edge_not_provable | must not be graded supported/strong | 25 | 0.250 | no | supported | 0.9669 | FAIL |
| short-edge/skewed/sr15/n45 | edge_not_provable | must not be graded supported/strong | 45 | 0.150 | no | weak | 0.9464 | pass |
| short-edge/skewed/sr10/n80 | edge_not_provable | must not be graded supported/strong | 80 | 0.100 | no | supported | 0.9835 | FAIL |
| short-edge/skewed/sr08/n150 | edge_not_provable | must not be graded supported/strong | 150 | 0.080 | no | indistinguishable_from_luck | 0.5901 | pass |
| short-edge/fat/sr30/n30 | edge_not_provable | must not be graded supported/strong | 30 | 0.300 | no | indistinguishable_from_luck | 0.8729 | pass |
| short-edge/fat/sr25/n25 | edge_not_provable | must not be graded supported/strong | 25 | 0.250 | no | indistinguishable_from_luck | 0.8290 | pass |
| short-edge/fat/sr15/n45 | edge_not_provable | must not be graded supported/strong | 45 | 0.150 | no | weak | 0.9516 | pass |
| short-edge/fat/sr10/n80 | edge_not_provable | must not be graded supported/strong | 80 | 0.100 | no | indistinguishable_from_luck | 0.1482 | pass |
| short-edge/fat/sr08/n150 | edge_not_provable | must not be graded supported/strong | 150 | 0.080 | no | indistinguishable_from_luck | 0.4792 | pass |
| regime/planted/normal/n180 | regime_planted | planted factor permutation p <= 0.05 | 180 | 0.172 | yes | indistinguishable_from_luck | 0.8421 | FAIL |
| regime/planted/normal/n300 | regime_planted | planted factor permutation p <= 0.05 | 300 | 0.099 | yes | indistinguishable_from_luck | 0.7819 | pass |
| regime/planted/skewed/n180 | regime_planted | planted factor permutation p <= 0.05 | 180 | 0.172 | yes | weak | 0.9096 | FAIL |
| regime/planted/fat/n300 | regime_planted | planted factor permutation p <= 0.05 | 300 | 0.123 | yes | indistinguishable_from_luck | 0.8839 | FAIL |
| regime/null/normal/n180 | regime_null | planted factor permutation p > 0.05 | 180 | 0.000 | no | indistinguishable_from_luck | 0.3446 | pass |
| regime/null/normal/n300 | regime_null | planted factor permutation p > 0.05 | 300 | 0.100 | yes | strong | 0.9939 | pass |
| regime/null/skewed/n180 | regime_null | planted factor permutation p > 0.05 | 180 | 0.000 | no | indistinguishable_from_luck | 0.7226 | pass |
| regime/null/fat/n300 | regime_null | planted factor permutation p > 0.05 | 300 | 0.100 | yes | supported | 0.9771 | pass |
| trap/constant-equity/a | degenerate | must return insufficient_evidence | 59 | 0.000 | no | insufficient_evidence | — | pass |
| trap/constant-equity/b | degenerate | must return insufficient_evidence | 59 | 0.000 | no | insufficient_evidence | — | pass |
| trap/three-points/a | degenerate | must return insufficient_evidence | 2 | 0.000 | no | insufficient_evidence | — | pass |
| trap/three-points/b | degenerate | must return insufficient_evidence | 2 | 0.000 | no | insufficient_evidence | — | pass |
| trap/duplicate-timestamps/a | degenerate | must return insufficient_evidence | 23 | 0.000 | no | insufficient_evidence | — | pass |
| trap/duplicate-timestamps/b | degenerate | must return insufficient_evidence | 23 | 0.000 | no | insufficient_evidence | — | pass |
| trap/unsorted-timestamps/a | degenerate | must return insufficient_evidence | 17 | 0.000 | no | insufficient_evidence | — | pass |
| trap/unsorted-timestamps/b | degenerate | must return insufficient_evidence | 17 | 0.000 | no | insufficient_evidence | — | pass |
