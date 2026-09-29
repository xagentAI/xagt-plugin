# AlphaLitmus Demo — Strategy Release Gate

This is a local demonstration protocol, not recorded live or external evidence. Start the REST service using the README, without a Nexus key. Never replace a missing deployment, strategy run or commit with a plausible placeholder claim.

The judge-first entry point is the release gate: `POST /v1/release-gate` and `GET /v1/release-gate/demo/{mixed,shock}`, plus MCP `evaluate_strategy_release`. The dashboard's first viewport shows the release decision first (decision, action, why, failures, unavailable evidence, IDs, Copy/Download JSON), with detailed research evidence below. Full agent contract: [AGENT-CALL-CONTRACT](AGENT-CALL-CONTRACT.md).

## Three-Minute Walkthrough

1. Open `/health` and `/v1/capabilities`. Explain that `local-dev` is intentionally not a public reviewed commit and that Nexus is disabled by default.
2. Fetch `/v1/demo/mixed`. This returns a complete `Report`, including a request with 900 synthetic candles generated from seed 812 beginning 2022-01-01. It is a certificate, not historical profit evidence.
3. Export the report's `request` and POST that object directly to `/v1/challenge`, or follow the README's explicit nested-research example. Show `UNPROVEN`, synthetic evidence classification, reason codes and unavailable tests. Do not cherry-pick positive metrics.
4. Inspect `analysis.folds`, `cost_frontier`, `delays`, `neighborhood`, `regimes`, `resampling`, and `minimal_failure_boundary`. Explain one failing perturbation or an already-failing baseline. A boundary is the smallest tested failure in one dimension, not a global optimum.
5. Repeat with `/v1/demo/shock`. Compare failures and limits, not a profitability ranking. The generator changes drift and volatility after index 720; both examples remain synthetic.
6. POST the complete report directly to `/v1/verify-report`, or verify an exported file with `python -m app.verify FILE`. Show that integrity validity does not make `UNPROVEN` profitable or authentic.
7. In a client-memory copy, change a metric and verify again. Explain checksum and replay checks; retain the untouched original. Do not overwrite legacy reports to stage the demonstration.
8. POST `{"mode":"nexus","symbol":"BTC/USDT"}` to `/v1/challenge` with Nexus disabled. Show missing evidence and `NEXUS_STRATEGY_NOT_REPLAYED`, not an invented successful live call.

## Agent Equivalent

Primary: MCP `evaluate_strategy_release` with `{"request":<ChallengeRequest>}` returns a `ReleaseGateResult` (`BLOCK_DEPLOYMENT`, `INSUFFICIENT_EVIDENCE`, `SURVIVED_BOUNDED_TESTS`) only when the source certificate verifies (`source_report_verified:true`); otherwise only `REPORT_VERIFICATION_FAILED`. REST equivalent is `POST /v1/release-gate` with the direct `ChallengeRequest`, or `GET /v1/release-gate/demo/mixed` for the safe synthetic demo (always `INSUFFICIENT_EVIDENCE`; observed failures stay visible but prove nothing about a real strategy).

Legacy detail path: use MCP `get_demo_fixture` with `{"scenario":"mixed"}`. It returns a full report. Pass that report's `request` to `challenge_nexus_strategy` as `{"request":<report.request>}`. Use the same nested arguments for `find_failure_boundary`; use `{"report":<report>}` for `verify_failure_certificate`. The placeholders must be replaced by actual returned objects. REST takes direct request/report bodies; MCP wraps them in named arguments. The full demo report is not a research input.

## Measured Local Results

Computed on 2026-09-19 by calling both actual REST demo routes through FastAPI `TestClient`, then passing each returned report to `verify_report`. Both verified. This is local synthetic execution, not a deployed API call, live Nexus evidence or a final test-suite result. No fixture, parameter, window or sample was tuned or excluded. Default requests used 10 bps fee plus 5 bps slippage, additional cost domain 0-100 bps in 1-bps steps, 200 bootstrap iterations, and null attempted-variant count and `as_of`.

All percentages below are rounded to six decimal places for display; reports retain the computed floating-point values. Both use training `[56,540)`, validation `[540,720)` and test `[720,900)`.

| Observed quantity | Mixed | Shock |
| --- | ---: | ---: |
| Verdict / eligibility | UNPROVEN / false | UNPROVEN / false |
| Guarded training return | 11.545631% | 11.545631% |
| Guarded validation return | -6.267049% | -6.267049% |
| Baseline test return | -0.918280% | -2.736946% |
| Guarded test return | -5.997141% | -8.455976% |
| Buy-and-hold test return | 9.704156% | -84.478186% |
| Baseline test drawdown | 14.520556% | 33.795708% |
| Guarded test drawdown | 14.520556% | 9.402432% |
| Guarded closed test trades | 3 | 1 |
| Guarded trade expectancy | -1.897827% | -8.455976% |
| Guarded profit factor | 0.445234 | 0.000000 |
| Return at +100 one-way bps | -11.471710% | -10.268760% |
| Profitable EMA neighbors | 0 of 9 | 0 of 9 |
| Delay 0 return | -5.997141% | -8.455976% |
| Delay 1 return | -2.405550% | 7.549899% |
| Delay 2 return | -1.624751% | 13.764846% |
| Delay 3 return | -0.666811% | 13.643610% |
| Descriptive bootstrap p05 | -17.634111% | -8.455976% |
| Descriptive bootstrap p95 | 7.283945% | -8.455976% |
| Descriptive permutation drawdown p95 | 10.104785% | 8.455976% |

Both have `resampling.status=insufficient` despite `bootstrap_status=available`; the numbers above do not become statistical passes. Shock's positive stale-signal delay trials are retained, but are not a reason to tune away the failing default. Its lower guarded drawdown also does not erase a worse return. Both cost frontiers have status `fails_at_baseline`; all four boundary statuses are `baseline_failure`, with zero delta and effect at additional cost 0, delay 0, fast EMA 20 and slow EMA 50.

Both reports preserve the same reason codes: `SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE`, `INSUFFICIENT_TEST_TRADES`, `INSUFFICIENT_BOOTSTRAP_TRADES`, `TEST_NOT_PROFITABLE`, `VALIDATION_NOT_PROFITABLE`, `GUARD_DID_NOT_IMPROVE_TEST_RETURN`, `COST_STRESS_NOT_PROFITABLE`, `DELAY_STRESS_NOT_PROFITABLE`, and `PARAMETER_NEIGHBORHOOD_UNSTABLE`.

Dataset hashes (not signatures or source attestations):

- Mixed: `7c5204bf52831353d854c9551f0429f24ecae7c490fa32a4ddf4407fd22a9be7`.
- Shock: `2679649617d6262813c5992aa7485eb5c33b21ce63c7ff375fd1c223cab1c1bf`.

Reproduce locally without fetching market data or writing reports:

```powershell
python -c "from fastapi.testclient import TestClient; from app.main import app; from app.certificates import verify_report; c=TestClient(app); reports=[c.get('/v1/demo/'+s).json() for s in ('mixed','shock')]; [print(r['dataset_sha256'], r['verdict'], r['analysis']['folds'][2]['guarded'], verify_report(r).valid) for r in reports]"
```

## Optional Real Evidence

Only an authorized owner may supply actual historical data and an external Nexus key. Preserve caller provenance labels, record acquisition and data rights separately, and distinguish imported reference data from the bound Nexus strategy. Nexus access requires the explicit enable switch and authenticated reverse proxy. No live step is asserted to have occurred here.

## Recorded Replay (separate from synthetic demo)

The dashboard adds “Replay real Nexus evidence →” (`GET /v1/nexus/replay/candidate-v1`, MCP `replay_recorded_nexus_evidence` with `{}`). It replays the sanitized recorded Candidate v1 snapshot through the real reconciliation/release-gate engine with no key and zero network calls. The captured production snapshot (aggregate `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8`) produces `INCONSISTENT`, `BLOCK_DEPLOYMENT`/`DO_NOT_DEPLOY`, `TRADE_SYMBOLS MISMATCH`, with capture time, strategy/run IDs, four surfaces, integrity `verified`, limitations, report ID, Copy/Download, and the disclosure that it is recorded historical evidence, not live, independently authenticated, or profit proof.

Pitch: an agent can tell a convincing strategy story; AlphaLitmus exposes bounded failure conditions and evidence gaps in a replayable report. It never promises an edge, investment safety, external acceptance or first place.
