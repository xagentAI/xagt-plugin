# Agent Call Contract — Strategy Release Gate

## One-line job

Before an agent deploys, enables, or scales a trading strategy, it calls AlphaLitmus to identify bounded fragility, contradictions, or insufficient evidence.

This is not a strategy generator, profitability predictor, trading bot, execution engine, financial adviser, or generic research dashboard.

## Who calls the tool

An autonomous trading agent (or its release orchestrator) that is about to:

- enable a strategy,
- change strategy configuration,
- increase risk or scale,
- continue running after a market-regime change,
- perform scheduled strategy revalidation.

The primary MCP tool is `evaluate_strategy_release`. The existing tools remain available for detail, verification, and bounded compute. A seventh read-only tool `replay_recorded_nexus_evidence` replays only the recorded Candidate v1 snapshot. An eighth read-only tool `evaluate_live_nexus_candidate` obtains a separately gated live pulse for that same fixed identity. Both accept no arguments.

## When it is called

- before enabling a strategy
- after changing strategy configuration
- before increasing risk or scale
- after a market-regime change
- during scheduled strategy revalidation

## Exact input / output

Input is the existing strict `ChallengeRequest` body.

REST:

```text
POST /v1/release-gate
Content-Type: application/json

{"mode":"nexus","symbol":"BTC/USDT"}
```

MCP (JSON-RPC envelope supplied by the client):

```json
{"name":"evaluate_strategy_release","arguments":{"request":{"mode":"nexus","symbol":"BTC/USDT"}}}
```

For reference mode, pass the demo report's `request` as `arguments.request`; do not put the whole report inside `research`. Unknown fields are rejected.

Output is the strict `ReleaseGateResult` (`alphalitmus-release-gate-1`):

```json
{
  "schema_version": "alphalitmus-release-gate-1",
  "decision": "BLOCK_DEPLOYMENT | INSUFFICIENT_EVIDENCE | SURVIVED_BOUNDED_TESTS",
  "recommended_action": "DO_NOT_DEPLOY | COLLECT_MORE_EVIDENCE | CONTINUE_PAPER_VALIDATION",
  "source_verdict": "FRAGILE | INCONSISTENT | UNPROVEN | SURVIVED_TESTS",
  "evidence_classification": "synthetic_reference | caller_labeled_historical_reference | nexus_snapshot | missing",
  "reason_codes": ["..."],
  "observed_failures": ["..."],
  "unavailable_tests": ["..."],
  "report_id": "<64-hex>",
  "canonical_report_hash": "<64-hex>",
  "no_execution": true,
  "profitability_claimed": false,
  "source_report_verified": true,
  "report": "<complete authoritative Report>",
  "disclaimer": "This result is not financial advice and is not deployment approval. SURVIVED_BOUNDED_TESTS means only survival of the stated bounded tests."
}
```

All lists and reason codes have deterministic (sorted) ordering. The projection never mutates the Report. There is no LLM call. A result is only issued when the existing `verify_report` accepts the source certificate (`source_report_verified: true`); invalid sources fail closed with sanitized `REPORT_VERIFICATION_FAILED` and no decision. `source_report_verified` is mandatory with no default: a missing field is rejected, never inferred as true, and only the exact JSON value `true` (not `1`, `"true"`, or any other coercion) is accepted. The dashboard enforces the same `=== true` boundary before display, copy, or download. Verification replays the bounded reference/reconciliation calculations, so expect roughly one challenge plus one verification replay per call.

Demo routes:

```text
GET /v1/release-gate/demo/mixed
GET /v1/release-gate/demo/shock
```

Recorded historical replay (credential-free, no arguments, fixed snapshot only):

```text
GET /v1/nexus/replay/candidate-v1
```

```json
{"name":"replay_recorded_nexus_evidence","arguments":{}}
```

The replay returns strict `RecordedNexusReplay` (`alphalitmus-recorded-replay-1`) with evidence identity (`SKLab AlphaLitmus Candidate v1`, `str_b840280ce037`, run `bt-7544746ff32d`, `BTC/USDT`, capture time), per-file and aggregate SHA-256, `snapshot_integrity:verified`, `integrity_scope:source_commit_bound_content_consistency_not_authenticity`, the embedded authoritative `ReleaseGateResult`, limitations, `historical:true`, `live:false`, `no_execution:true`, `profitability_claimed:false`, and the disclosure that it is recorded historical evidence, not a live call or profit proof. REST accepts no body or query parameters. REST and MCP share `app.transport.run_recorded_replay`; outputs are identical after transport wrapping. The fixed strategy ID is operator-asserted from the strategy-bound key because Nexus read surfaces do not return it. Missing evidence returns `503 RECORDED_EVIDENCE_UNAVAILABLE`; tampering returns `500 RECORDED_EVIDENCE_INVALID`/`RECORDED_EVIDENCE_INTEGRITY_FAILED`, with no synthetic fallback. The checked-in snapshot was captured at `2026-09-19T18:45:48+00:00`, aggregate `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8`, and locally verified through identical REST/MCP replay.

Unknown scenarios return 404 `UNKNOWN_SCENARIO`. There is no persisted report-list API; retain `report_id`, canonical hash, and exported JSON via Copy JSON / Download JSON.

Fixed live pulse (no request body/query and strict empty MCP arguments):

```text
GET /v1/nexus/live/candidate-v1
```

```json
{"name":"evaluate_live_nexus_candidate","arguments":{}}
```

The result is strict `LiveNexusResult` (`alphalitmus-live-nexus-1`) for `SKLab AlphaLitmus Candidate v1`, `str_b840280ce037`, `BTC/USDT`. It reports per-surface fetch times and freshness, cache status/age/TTL, latency, the authoritative verified `ReleaseGateResult`, and exact safety flags: `live:true`, `historical:false`, `no_execution:true`, `profitability_claimed:false`, `recorded_fallback_used:false`. An unavailable upstream returns only a bounded `LIVE_NEXUS_*` error; recorded evidence is never substituted. The tool is read-only/non-destructive but has `idempotentHint:false`, `openWorldHint:true` because a call can refresh external evidence.

## Decision semantics

| Source verdict | Release decision | Recommended action |
| --- | --- | --- |
| `FRAGILE` | `BLOCK_DEPLOYMENT` | `DO_NOT_DEPLOY` |
| `INCONSISTENT` | `BLOCK_DEPLOYMENT` | `DO_NOT_DEPLOY` |
| `UNPROVEN` | `INSUFFICIENT_EVIDENCE` | `COLLECT_MORE_EVIDENCE` |
| `SURVIVED_TESTS` | `SURVIVED_BOUNDED_TESTS` | `CONTINUE_PAPER_VALIDATION` |

Never returned: `APPROVE_DEPLOYMENT`, `EXECUTE`, `BUY`, `SELL`, `PROFITABLE`, `SAFE_TO_TRADE`, or equivalent wording.

- `BLOCK_DEPLOYMENT` means bounded counterevidence was observed. Do not deploy.
- `INSUFFICIENT_EVIDENCE` means the gate cannot decide; collect more authentic evidence and continue paper validation.
- `SURVIVED_BOUNDED_TESTS` means only survival of the stated bounded tests.

## Safety boundary

- Synthetic evidence can never become authentic or profitable evidence.
- `UNPROVEN` is never presented as success.
- `SURVIVED_TESTS` means only survival of the bounded tests, not deployment approval or proof of future profitability.
- `FRAGILE` and `INCONSISTENT` remain distinct underlying verdicts.
- Missing or unavailable evidence fails closed.
- AlphaLitmus never places trades or signs transactions.
- Public safe mode keeps Nexus and remote backtest compute disabled.
- Never fabricate a Nexus result, strategy, run, source timestamp, deployment, test outcome, or report URL.
- Never expose or request a Nexus API key.
- Existing reports and certificate verification remain authoritative.
- REST and MCP share the same service function (`app.transport.run_release_gate`) and decision mapping; there is no parallel analysis implementation.

## Safe failure behavior

- Bodies limited to 4,000,000 bytes, JSON depth 32, 10-second body deadline, 8 intake slots and 2 compute slots per process are reused from the existing transport.
- Schema-invalid input returns 422 `INVALID_REQUEST` without echoing raw input.
- Malformed, duplicate-key, oversized, or nonfinite frames are rejected with sanitized codes (`INVALID_JSON`, `BODY_TOO_LARGE`, `CAPACITY_EXCEEDED`, `INVALID_ARGUMENTS`, `TOOL_FAILED`).
- Unknown demo scenarios return 404 `UNKNOWN_SCENARIO`.
- Missing Nexus evidence returns `UNPROVEN` / `INSUFFICIENT_EVIDENCE` with `MISSING_NEXUS_EVIDENCE`, never an invented success.
- An invalid source certificate returns only `REPORT_VERIFICATION_FAILED` (REST: HTTP 500 `{"detail":"REPORT_VERIFICATION_FAILED"}`; MCP: `ToolError` with the same code) with no traceback, metrics, request data, paths, or certificate contents.

## One REST example

```powershell
$base = 'http://127.0.0.1:8040'
$gate = Invoke-RestMethod "$base/v1/release-gate/demo/mixed" -Method Get
$gate.decision        # INSUFFICIENT_EVIDENCE for the synthetic demo
$gate.recommended_action
$gate.report_id
```

Reference-mode release check (reuse the demo request):

```powershell
$request = $gate.report.request | ConvertTo-Json -Depth 20
Invoke-RestMethod "$base/v1/release-gate" -Method Post -ContentType 'application/json' -Body $request
```

## One MCP example

```json
{"name":"evaluate_strategy_release","arguments":{"request":{"mode":"nexus","symbol":"BTC/USDT"}}}
```

Reference mode:

```json
{"name":"evaluate_strategy_release","arguments":{"request":{"mode":"reference","symbol":"BTC/USDT","research":{...},"additional_cost_max_bps":100.0,"cost_resolution_bps":1.0,"bootstrap_iterations":200}}}
```

Tool annotations: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=true`.

## Why SURVIVED_BOUNDED_TESTS is not deployment approval

`SURVIVED_BOUNDED_TESTS` restates `SURVIVED_TESTS`: the strategy survived the fixed EMA cost, delay, parameter, resampling, and regime checks over the supplied window. It does not validate the Nexus-bound strategy, prove a future edge, clear selection bias, model intraday risk, funding, capacity, or order-book effects, or authorize live trading. The recommended action is `CONTINUE_PAPER_VALIDATION`, never deployment.

## Why synthetic demos remain INSUFFICIENT_EVIDENCE

Public demos use seeded synthetic fixtures (seed 812). The engine labels them `synthetic_reference` and forces `UNPROVEN` via `SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE`, even when observed failures exist. The projection therefore returns `INSUFFICIENT_EVIDENCE` / `COLLECT_MORE_EVIDENCE`. Observed counterevidence stays visible for inspection, but a synthetic demo never proves a real strategy is fragile, profitable, safe, or ready to deploy. More authentic evidence is required.
