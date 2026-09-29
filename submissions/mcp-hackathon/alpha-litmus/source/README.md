# AlphaLitmus — Strategy Release Gate for Agents

Before an agent deploys, enables, or scales a trading strategy, it calls AlphaLitmus to identify bounded fragility, contradictions, or insufficient evidence. Product slug: `alpha-litmus`.

Bounded strategy failure experiments, conditional Nexus reconciliation, and independently replayable certificates. The primary capability is `evaluate_strategy_release`; it reuses the existing analysis and certificate engine with no parallel implementation. See [agent call contract](docs/AGENT-CALL-CONTRACT.md).

AlphaLitmus tests a fixed daily EMA reference strategy against cost, delay and parameter perturbations. It can separately reconcile four read-only Nexus evidence surfaces and, with explicit opt-in, submit bounded Nexus backtest window experiments. **The reference strategy is not the Nexus-bound strategy.** The new compute tool has remote side effects; the service as a whole is not read-only. No orders, strategy creation, wallet signing, profit prediction or position sizing is implemented.

Verdicts are `UNPROVEN`, `FRAGILE`, `SURVIVED_TESTS` and `INCONSISTENT`. Synthetic inputs stay unproven. Survival means only survival of the stated bounded tests, not a validated edge. Certificates verify internal consistency, not data authenticity or authorship. No PSR or selection-adjusted significance is computed.

## Local Setup

Python 3.12 is the supported runtime. From this project directory on Windows:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m mypy app
.venv/Scripts/python -m tools.local_smoke
.venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8040
```

Runtime-only installs use `requirements.txt`, which includes the MCP SDK. Open `/` for the dashboard and `/docs` or `/openapi.json` for the API contract. `.env.example` documents configuration; it is not loaded automatically. Final test counts are intentionally not recorded here. See [baseline](docs/BASELINE.md) and [release readiness](docs/RELEASE-READINESS.md).

## REST Contract

| Method and path | Input | Output |
| --- | --- | --- |
| `GET /health` | None | Status, service, commit, reviewability and provenance caveat |
| `GET /.well-known/xagent-verification.json` | None | Schema version, slug and commit claim |
| `GET /v1/capabilities` | None | Eight tool names, fixed live-candidate availability, `opt_in_nexus_backtest_compute` side effect, arbitrary Nexus read switch and transport limits |
| `GET /v1/release-gate/demo/mixed` or `/v1/release-gate/demo/shock` | None | Synthetic `ReleaseGateResult` (`INSUFFICIENT_EVIDENCE`); embeds the complete `Report` as `report` |
| `POST /v1/release-gate` | Direct `ChallengeRequest` | Strict `ReleaseGateResult` with decision, action, `source_report_verified: true`, and complete `report`; invalid source certificates fail closed with sanitized `REPORT_VERIFICATION_FAILED` |
| `GET /v1/nexus/replay/candidate-v1` | None | Recorded historical Nexus replay (`alphalitmus-recorded-replay-1`); no key required; unavailable without production snapshot |
| `GET /v1/nexus/live/candidate-v1` | None | Fixed Candidate v1 live pulse (`alphalitmus-live-nexus-1`); four read-only surfaces, verified release gate, disclosed 60-second cache; no body/query |
| `GET /v1/demo/mixed` or `/v1/demo/shock` | None | Complete synthetic `Report`; replay input is `report.request` |
| `POST /v1/challenge` | Direct `ChallengeRequest` | Complete current `Report` |
| `POST /v1/find-failure-boundary` | Direct `ChallengeRequest` | Same complete report, including per-dimension boundaries |
| `POST /v1/verify-report` | Direct complete `Report` | `valid`, report ID, errors, `authenticity_verified: false` |
| `POST /v1/nexus/window-stability` | Direct `WindowExperimentRequest` | Separate `WindowExperimentReport`; explicitly confirmed remote compute, never trading |
| `POST /v1/research` | Direct `ResearchRequest` | Deprecated legacy research report |
| `POST /v1/audit` | `{"symbol":"BTC/USDT"}` | Deprecated fail-closed legacy audit |

Release-gate decisions: `FRAGILE`/`INCONSISTENT` → `BLOCK_DEPLOYMENT`/`DO_NOT_DEPLOY`; `UNPROVEN` → `INSUFFICIENT_EVIDENCE`/`COLLECT_MORE_EVIDENCE`; `SURVIVED_TESTS` → `SURVIVED_BOUNDED_TESTS`/`CONTINUE_PAPER_VALIDATION`. `SURVIVED_BOUNDED_TESTS` is not deployment approval. Synthetic demos remain `INSUFFICIENT_EVIDENCE`. The dashboard shows the release decision first with Copy JSON / Download JSON; there is no durable report URL.

There is no persisted report-list/retrieval API in the inspected source. Retain returned JSON through your client or dashboard export. REST verification takes the report itself, **not** `{"report": ...}`. A schema-invalid report receives 422 before verification; a schema-valid inconsistent report returns a verification result with `valid: false`.

A complete executable synthetic challenge, without embedding hundreds of candles in this README:

```powershell
$base = 'http://127.0.0.1:8040'
$demo = Invoke-RestMethod "$base/v1/demo/mixed"
$research = $demo.request.research
$request = @{
    mode = 'reference'
    symbol = 'BTC/USDT'
    research = $research
    attempted_variants = $null
    additional_cost_max_bps = 100.0
    cost_resolution_bps = 1.0
    bootstrap_iterations = 200
    as_of = $null
}
$body = $request | ConvertTo-Json -Depth 20
$report = Invoke-RestMethod "$base/v1/challenge" -Method Post -ContentType 'application/json' -Body $body
$certificate = $report | ConvertTo-Json -Depth 30
Invoke-RestMethod "$base/v1/verify-report" -Method Post -ContentType 'application/json' -Body $certificate
```

Alternatively, replay the unchanged demo by serializing `$demo.request` directly; exporting `report.request` gives a complete `ChallengeRequest`, while `report.request.research` is the nested research input. Use the same `$body` with `/v1/find-failure-boundary`. An offline/local missing-evidence Nexus request is `{"mode":"nexus","symbol":"BTC/USDT"}`; `research` must be absent or null. Explicit `as_of` Unix seconds is required to assess certificate freshness; otherwise freshness is unavailable. Do not add a Nexus key merely to run the synthetic demo.

`research` contains required `candles` and `data_kind`, plus `symbol`, `source`, `fee_bps`, `slippage_bps`. Each candle is `{t,o,h,l,c,v}`. Supply 250-3000 closed, gap-free UTC daily bars; timestamps are opening milliseconds. Reference challenge prices must lie within [1e-8,1e12] with dataset maximum/minimum ratio <= 1e6. Both cost fields are one-way bps in [0,200]. Extra fields, invalid OHLC, nonfinite values and secret-like source labels are rejected. Exact domains and formulas are in [methodology](docs/METHODOLOGY.md).

Bodies are limited to 4,000,000 bytes and JSON depth 32. Duplicate keys and nonfinite JSON are rejected. HTTP intake admits eight requests per process and holds each slot through dispatch; receiving the entire body has a 10-second deadline. Expensive work separately admits two operations per process. Errors include 400 invalid JSON/request, 408 `BODY_TIMEOUT`, 413 oversized body, 415 unsupported encoding/content type, 422 invalid contract, and 429 `CAPACITY_EXCEEDED`. These gates are not authentication or distributed rate limiting. `GET /health` bypasses intake and compute admission and never reads or waits for an upload; declared bodies are rejected, while undeclared bytes are not read or buffered. Unknown demo scenarios return 404. Error responses do not echo raw validation input.

## Reports and Verification

Challenge certificates (`Report`, not the separate window-compute report) carry the exact request, candle hash, evidence classification, eligibility, reason codes, observed failures, test matrix, unavailable tests, per-dimension failure boundaries, analysis or reconciliation, limitations and provenance. `report_id` and `canonical_report_hash` identify canonical content excluding creation time and the hash fields themselves. `nexus_validated` and `authenticity_claimed` remain false; `no_execution` remains true. That field and health's `no_execution` must not be interpreted as a service-wide promise of no backtest compute.

Verify an exported current certificate without a server or Nexus connection:

```powershell
python -m app.verify path/to/certificate.json
```

The CLI prints JSON and exits 0 for valid or 1 for invalid, unreadable or incorrectly invoked input. It replays calculations, not just the checksum. A self-consistent forged dataset can still verify. Legacy `reports/` files are unchanged negative artifacts, not current certificates; their original provenance and results are described in [BASELINE](docs/BASELINE.md).

The optional historical acquisition command is `python -m tools.fetch_history`, run from the project root. It contacts Binance's public data API for the fixed 2022-01-01 through 2025-12-31 BTCUSDT daily window and generates **legacy** research outputs. It overwrites the three existing `reports/` artifacts, so do not run it in this preserved workspace. Use a separate authorized working copy when acquisition is wanted. It was not run for this update; no historical data or legacy provenance was replaced.

## MCP

Run `python -m app.mcp_server` with this directory as the MCP host's working directory. Use the intended Python interpreter as command and `-m app.mcp_server` as arguments. Transport is stdio, not a deployed Streamable HTTP endpoint. Runtime requirements already include MCP.

| Tool | Exact `arguments` shape | Result |
| --- | --- | --- |
| `evaluate_strategy_release` (primary) | `{"request": <ChallengeRequest>}` | Strict `ReleaseGateResult`; `BLOCK_DEPLOYMENT`, `INSUFFICIENT_EVIDENCE`, or `SURVIVED_BOUNDED_TESTS` |
| `challenge_nexus_strategy` | `{"request": <ChallengeRequest>}` | Complete report; reference or Nexus mode |
| `find_failure_boundary` | `{"request": <ChallengeRequest>}` | Complete report with bounded frontier |
| `verify_failure_certificate` | `{"report": <Report>}` | Verification result |
| `get_demo_fixture` | `{"scenario":"mixed"}` or `{"scenario":"shock"}`; default mixed | Complete synthetic `Report` |
| `run_nexus_window_stability` | `{"request": <WindowExperimentRequest>}` | Separate window report; remote backtest compute side effect, not trading |
| `replay_recorded_nexus_evidence` | `{}` (strict empty, extra forbid) | Recorded historical replay; same `RecordedNexusReplay` as REST; no key, no network |
| `evaluate_live_nexus_candidate` | `{}` (strict empty, extra forbid) | Fixed Candidate v1 live Nexus pulse; same `LiveNexusResult` as REST; no trading or recorded fallback |

Angle-bracket entries in this table are schema placeholders, not literal JSON. The primary no-key call is:

```json
{"name":"evaluate_strategy_release","arguments":{"request":{"mode":"nexus","symbol":"BTC/USDT"}}}
```

For reference mode, pass the demo report's `request` as `arguments.request`; do not put the whole report inside `research`. Both challenge tools and the primary release-gate tool require the outer `request`; flattened candle arguments are invalid. REST (`POST /v1/release-gate`) and MCP (`evaluate_strategy_release`) share `app.transport.run_release_gate` and the same decision mapping. Successful release-gate decisions are only issued from a source certificate accepted by the existing `verify_report`; otherwise both surfaces return only the sanitized `REPORT_VERIFICATION_FAILED` code. Verification replays the bounded reference/reconciliation calculations, so a release-gate call costs roughly one challenge plus one verification replay. Unknown arguments are rejected rather than coerced/ignored. Raw stdio frames are bounded to 4,000,000 bytes before SDK decoding; malformed, duplicate-key or oversized frames close the session without trusting their request ID. Tool failures use sanitized errors.

The primary release-gate tool plus the original four tools retain read-only behavior and backward-compatible argument wrappers. They are annotated `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true` (primary: `openWorldHint=true`). The sixth tool (`run_nexus_window_stability`) is annotated `readOnlyHint=false`, `idempotentHint=false`, `destructiveHint=false`, `openWorldHint=true`: it starts remote backtests, not trades. Do not automatically retry it. The seventh tool (`replay_recorded_nexus_evidence`) is read-only, idempotent and closed-world. The eighth (`evaluate_live_nexus_candidate`) is read-only/non-destructive but `idempotentHint=false`, `openWorldHint=true` because it can refresh external Nexus evidence; clients should respect its cache and rate limits.

## Fixed live Nexus pulse

`GET /v1/nexus/live/candidate-v1` and MCP `evaluate_live_nexus_candidate` accept no arguments and are locked to `SKLab AlphaLitmus Candidate v1` (`str_b840280ce037`, `BTC/USDT`). They call only the four existing read-only Nexus evidence surfaces, require all four fresh envelopes, run the normal certificate plus verified release-gate path, and return exact flags `live:true`, `historical:false`, `no_execution:true`, `profitability_claimed:false`, `recorded_fallback_used:false`. Upstream failure never falls back to the recorded snapshot.

The endpoint is separately gated by `ALPHALITMUS_ENABLE_LIVE_NEXUS=true` and a bounded key loaded from `NEXUS_API_KEY_FILE` (or `NEXUS_API_KEY` for local operator use). The arbitrary caller-selected Nexus endpoints remain disabled when `ALPHALITMUS_ENABLE_NEXUS=false`. Successful results use a disclosed 60-second in-process cache; intake is capped at 30 requests/minute/process, refresh attempts are spaced by 10 seconds, and three consecutive failures open a 120-second circuit. These are operational safeguards, not authentication or distributed quotas. Live freshness proves only when the four envelopes were fetched; it is not Nexus authorship attestation, trading authorization, or evidence of future profitability.

## Recorded Nexus Evidence Replay (credential-free, historical)

Status: CAPTURED AND VERIFIED — the production `evidence/nexus-candidate-v1/` snapshot was captured through the four read-only Nexus surfaces at `2026-09-19T18:45:48+00:00`. Aggregate snapshot SHA-256: `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8`. The key was environment-only and removed after capture; the committed evidence contains only sanitized canonical JSON. Local REST and MCP replay are identical and produce `INCONSISTENT`, `BLOCK_DEPLOYMENT`/`DO_NOT_DEPLOY`, and `TRADE_SYMBOLS MISMATCH` with `source_report_verified:true`.

Recorded versus live: the replay is a recorded historical Nexus snapshot for `SKLab AlphaLitmus Candidate v1` (`str_b840280ce037`, run `bt-7544746ff32d`, `BTC/USDT`), not a live Nexus call, not independent attestation, not proof of profitability, and not trading authorization.

Capture (operator with authorized strategy-bound key only):

```powershell
python -m tools.capture_nexus_snapshot
```

The tool is locked to the repository-owned `evidence/nexus-candidate-v1/` destination and the four fixed Candidate v1 identity constants; alternate identities, arbitrary output paths, links, and unexpected overwrite trees are rejected before any Nexus call. It reuses `app.nexus.read_nexus` (four read-only tools only), requires all four surfaces `received`, verifies equity/trades run binding, persists only sanitized canonical JSON plus `manifest.json`, and fails closed with staged writes plus the repository's complete secret scanner. The aggregate SHA-256 binds all manifest metadata and per-file hashes. It never prints the key. These hashes establish source-commit-bound content consistency, not Nexus authorship or authenticity; the strategy ID remains an operator assertion from the strategy-bound key because the read surfaces do not return it.

Replay (reviewer, no key):

```powershell
Invoke-RestMethod http://127.0.0.1:8040/v1/nexus/replay/candidate-v1 -Method Get
```

MCP: `{"name":"replay_recorded_nexus_evidence","arguments":{}}`. Both share `app.transport.run_recorded_replay` and return identical strict `RecordedNexusReplay` content. REST accepts neither a request body nor query parameters. Without the production snapshot the endpoint returns `503 RECORDED_EVIDENCE_UNAVAILABLE`; tampering returns `500 RECORDED_EVIDENCE_INVALID` or `RECORDED_EVIDENCE_INTEGRITY_FAILED`. Expected genuine behavior (once captured): `INCONSISTENT`, `BLOCK_DEPLOYMENT`/`DO_NOT_DEPLOY`, `TRADE_SYMBOLS MISMATCH`, `source_report_verified:true`, `no_execution:true`, `profitability_claimed:false`. Documented reconciliation hash: `5b59fa3e55d1417d932b201da63cd505b55e53a9662e8c0daea3e17335838e25`. See [Nexus live evidence](docs/NEXUS-LIVE-EVIDENCE.md).

## Nexus Window Compute

All four gates are required: `ALPHALITMUS_ENABLE_NEXUS=true`, `ALPHALITMUS_ENABLE_NEXUS_BACKTEST=true`, an externally injected `NEXUS_API_KEY`, and the request's literal JSON boolean `confirm_compute: true`. The key selects an existing strategy with a prior Studio **Fire Backtest**. No strategy definition or deploy JSON is accepted. Defaults leave compute disabled; no real key is needed for local demos, fixture tests or documentation review.

Exact REST body for `POST /v1/nexus/window-stability` with `Content-Type: application/json`:

```json
{"confirm_compute":true,"symbol":"BTC/USDT","windows":[100,250,500],"timeout_seconds":30}
```

Exact MCP tool-call payload (the surrounding JSON-RPC envelope is supplied by the MCP client):

```json
{"name":"run_nexus_window_stability","arguments":{"request":{"confirm_compute":true,"symbol":"BTC/USDT","windows":[100,250,500],"timeout_seconds":30}}}
```

These examples authorize compute only if the server is also enabled and configured. With default-disabled settings, a valid request returns `UNPROVEN` with `NEXUS_COMPUTE_DISABLED` and no network call. With both switches enabled but no valid key, it returns `NEXUS_NOT_CONFIGURED`. `nexus_enabled` in capabilities reports the read switch only, not compute readiness.

Windows must be 1-3 unique ascending integers in 20..500; execution is descending, default 500 then 250 then 100, with baseline 500. Polling sleeps one second before each poll. The entire experiment has a 30-second default timeout, configurable from 5 to 60 seconds, and permits only one experiment per process. There are no retries or remote cancellation guarantees; Studio and other processes can race this service. Run-ID contradictions fail closed.

Metrics and signals are not run-attested. Window reports can only be `UNPROVEN` or `INCONSISTENT`, never a success/survival claim: `confirmed_counterexample=false`, `baseline_survived=null`, `definitive_boundary_n_bars=null`. `smallest_observed_failing_n_bars` is only the minimum sampled window with an observed cached-metric failure, not a confirmed boundary. Listing qualification is not independent profitability evidence. This path never reuses the local EMA as the bound strategy. See [window stability](docs/NEXUS-WINDOW-STABILITY.md) for exact upstream requests, inference limits and operational quotas.

## Deployment

The Dockerfile uses `python:3.12-slim`, UID 10001, port 8040, OCI metadata and a standard-library HTTP healthcheck. It copies runtime requirements and `app`, not local reports, test data or secrets. The base tag is mutable, not a claimed reproducible image digest.

```powershell
docker build -t alpha-litmus .
docker run --rm -p 127.0.0.1:8040:8040 alpha-litmus
```

For production, build with `--build-arg ALPHALITMUS_COMMIT=<actual-reviewed-40-hex-commit>` and set `ALPHALITMUS_ENV=production` at runtime. Replace that placeholder with a real nonzero lowercase commit, never a fabricated one. `commit_reviewable=false` pairs only with `commit="local-dev"`; true means nonzero lowercase 40-hex syntax only, not Git existence, source authenticity or build attestation. Missing/invalid development configuration falls back to `local-dev`; production rejects that fallback at startup.

Enable Nexus reads only with **`ALPHALITMUS_ENABLE_NEXUS=true`**, an externally injected `NEXUS_API_KEY` bound to an authorized completed Nexus strategy/backtest, and an **authenticated, rate-limiting TLS reverse proxy**. Compute additionally needs the backtest switch and per-request confirmation above. Neither flags nor confirmation authenticate callers. Enforce explicit per-principal compute quotas and a gateway-wide concurrency/submission limit across workers before exposing compute. Keep health and proof public as required for review; protect capability routes. The fixed upstream endpoint is `https://nexus.olaxbt.xyz/api/mcp/tools/call`, using `X-API-KEY`. The four evidence reads remain separate from the new `run_backtest` and `get_backtest_job` operations. One explicitly authorized local read-only MCP reconciliation has been performed; it returned `INCONSISTENT` and used an in-memory key. See [Nexus live evidence](docs/NEXUS-LIVE-EVIDENCE.md).

Health service and deployment-proof slug are both `alpha-litmus`.
`ALPHALITMUS_COMMIT` is the only commit environment variable; there is no legacy
fallback. The local Windows daemon was unreachable, but the target Linux VPS
subsequently built and ran the safe-mode image successfully with Nexus disabled.
The public HTTPS edge is live and the active safe-mode release is bound to the
same 40-character public commit reported by `/health` and the well-known proof.
See [VPS deployment](docs/VPS-DEPLOYMENT.md).

## Evidence Status

A public safe-mode API, judge UI, and source repository are available, but no profitable-strategy validation, rights clearance, registration proof, official validator success or contest acceptance is claimed. Real Studio runs and one callable read-only Nexus MCP snapshot exist; AlphaLitmus classified the candidate `INCONSISTENT` because its recent trades crossed instruments. Do not infer ownership or data-use rights from file availability.

Dependency license metadata and the inventory document third-party evidence only. They do not grant a project license, establish project ownership, or clear source, data or branding rights. Current aggregate gate results (fixed-live-pulse hardening local run, Python 3.12.10): 680 passed with 1 warning, Ruff clean, strict mypy clean (18 source files), `pip check` clean, secret scan exit 0, local smoke exit 0 (8 MCP tools; artifacts under the run's temporary directory), isolated pip-audit reporting no known vulnerabilities for `requirements.txt`, and a healthy hardened target-VPS container behind verified public HTTPS. The current Windows Docker daemon was unavailable, so the revised live-pulse image awaits the target-VPS build. Successful release-gate decisions require a verified source certificate. The redesigned UI previously received a Chromium browser pass at desktop and 390×844 mobile viewports; the new live-pulse panel has static/TestClient and JavaScript syntax coverage but still needs the post-deploy browser pass. This is not formal accessibility or cross-browser certification. The active health and proof endpoints report the same public 40-character source commit.

- [Demo](docs/DEMO.md): repeatable local presentation with negative and unavailable results.
- [Methodology](docs/METHODOLOGY.md): exact formulas, thresholds, bootstrap assumptions and citations.
- [Threat model](docs/THREAT-MODEL.md): trust boundaries and operating requirements.
- [Competitive position](docs/COMPETITIVE-POSITION.md): category distinctions without unsupported superiority claims.
- [Nexus live evidence](docs/NEXUS-LIVE-EVIDENCE.md): exact Studio strategy/run binding and the live MCP contradiction AlphaLitmus detected.
- [VPS deployment](docs/VPS-DEPLOYMENT.md): executed safe-mode container build, hardening evidence and verified public HTTPS edge.
- [Submission checklist](docs/SUBMISSION-CHECKLIST.md): official sources reviewed 2026-09-19, remaining external evidence.
- [Release readiness](docs/RELEASE-READINESS.md): quality gates and limitations.
