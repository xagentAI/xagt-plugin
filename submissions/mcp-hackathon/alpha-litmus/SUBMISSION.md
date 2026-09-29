# AlphaLitmus

**Track:** OlaXBT × X-Agent Trading Challenge

## Capability

- **One-line description:** Give agents a verified release decision before they deploy or scale a trading strategy, backed by bounded falsification tests and a replayable evidence certificate.
- **Trading-track qualification:** AlphaLitmus was built around named OlaXBT Nexus strategies and completed backtest runs. It reconciles Nexus signal, metrics, equity, and recent-trade evidence into a fail-closed release decision; it is not a strategy-only, backtest-only, or simple API-wrapper submission.
- **Who it helps:** Trading agents, strategy researchers, and reviewers who need to challenge a strategy before capital is exposed.
- **Capability boundary:** AlphaLitmus replays a fixed reference strategy against costs, execution delay, chronological folds, parameter perturbations, bootstrap diagnostics, and market regimes. It also offers a live, read-only four-surface Nexus pulse locked to Candidate v1, replays a sanitized historical snapshot, and can optionally request bounded Nexus backtest windows. It never places orders, signs wallets, predicts profit, promotes a strategy to live trading, or treats a synthetic fixture as market evidence.

## Live API

- **API base URL:** https://alphalitmus.sklab.cc
- **Health-check URL:** https://alphalitmus.sklab.cc/health
- **Authentication:** None for the public review deployment. Live Nexus access is restricted by code to the fixed Candidate v1 identity; caller-selected Nexus reads and remote backtest compute remain disabled.
- **Rate limits / known limits:** JSON bodies are limited to 4,000,000 bytes and depth 32. Each process admits at most eight intake requests and two expensive operations; body receipt has a 10-second deadline. The live pulse uses a disclosed 60-second cache, 30 requests/minute/process, a 10-second minimum refresh interval, and a three-failure/120-second circuit breaker. Reviewers should avoid load testing.
- **API contract:** Interactive OpenAPI is at https://alphalitmus.sklab.cc/docs, the machine-readable contract is at https://alphalitmus.sklab.cc/openapi.json, and the implementation is in `source/app/`. A local stdio MCP server exposes eight tools documented in `source/README.md`; the primary agent tool is `evaluate_strategy_release`, `evaluate_live_nexus_candidate` runs the fixed live pulse, and `replay_recorded_nexus_evidence` provides credential-free historical replay.

## Source and reproducibility

- **Source repository:** https://github.com/ShahadatTest/alpha-litmus
- **Review commit:** `00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f`
- **Source submitted in this PR:** `source/`
- **Run tests:** `python -m pip install -r requirements-dev.txt && python -m pytest -q && python -m ruff check . && python -m mypy app`
- **Run locally:** `python -m pip install -r requirements.txt && python -m uvicorn app.main:app --host 127.0.0.1 --port 8040`
- **Deploy:** `docker build --build-arg ALPHALITMUS_COMMIT=00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f -t alpha-litmus .` followed by a hardened container run with `ALPHALITMUS_ENV=production`; the exact production controls are in `source/docs/VPS-DEPLOYMENT.md`.
- **Version binding:** The image is built from `git archive` of the review commit with the same commit passed as `ALPHALITMUS_COMMIT`. Both public health and same-origin proof expose it. The response also states that syntax is not independent build attestation.

The deployed API exposes:

```json
{"commit":"00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f","commit_reviewable":true,"status":"ok","service":"alpha-litmus","no_execution":true,"provenance_basis":"syntax_only_not_authenticated"}
```

```json
{"commit":"00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f","commit_reviewable":true,"schemaVersion":1,"slug":"alpha-litmus","provenance_basis":"syntax_only_not_authenticated"}
```

## Verification

The exact public calls, expected invariants, and safe failure behavior are in `verification/README.md`.

- **Health-check result:** Public HTTPS returns HTTP 200, `status: ok`, and the exact review commit.
- **Capability call:** `GET /v1/release-gate/demo/mixed` performs the complete bounded synthetic challenge, verifies its source certificate, and projects it into the strict agent-facing release contract. The verified public run returned `INSUFFICIENT_EVIDENCE` with `COLLECT_MORE_EVIDENCE`, `source_report_verified: true`, and the complete authoritative report instead of claiming a profitable edge.
- **Recorded Nexus evidence:** `GET /v1/nexus/replay/candidate-v1` performs zero live network calls and replays the checked-in sanitized snapshot from signal, metrics, equity, and recent trades. The public result is `INCONSISTENT`, `BLOCK_DEPLOYMENT`, `DO_NOT_DEPLOY`, and `TRADE_SYMBOLS MISMATCH`, with aggregate snapshot hash `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8` and `source_report_verified: true`.
- **Live Nexus pulse:** `GET /v1/nexus/live/candidate-v1` fetches signal, metrics, equity, and trades for fixed strategy `str_b840280ce037` and `BTC/USDT`, then returns the verified release gate with per-surface freshness and disclosed cache state. The deployed check returned `INCONSISTENT`, `BLOCK_DEPLOYMENT`, `DO_NOT_DEPLOY`, exact `source_report_verified:true`, `live:true`, `historical:false`, and `recorded_fallback_used:false`.
- **Expected error behavior:** A schema-invalid challenge such as `{}` returns HTTP 422 with the bounded body `{"detail":"INVALID_REQUEST"}`. Missing Nexus access returns an evidence-labelled unavailable result; it is not converted into validation.

## Security and data handling

- **Data collected:** Challenge requests and generated reports are processed in memory. The service has no report-list or persisted report-retrieval API. A returned/exported report contains the caller's submitted research data, so callers must review it before sharing.
- **Purpose and retention:** Inputs are used only to compute the requested analysis and response. The submitted implementation does not provide application-level persistence or a retention guarantee; reverse-proxy/container logs may retain ordinary request metadata under operator policy.
- **Third parties / outbound network calls:** The fixed live pulse contacts only the OlaXBT Nexus MCP endpoint through four read-only calls. Caller-selected Nexus reads and remote compute remain disabled. The optional historical-data tool contacts Binance and is not part of the public demo path.
- **Secrets:** No secrets are committed. The strategy-bound Nexus key is mounted from a root-owned, read-only VPS secret file and is never returned by the API, embedded in the image, or placed in container environment output.
- **Known risks / restrictions:** The public safe-mode routes are unauthenticated and are not intended for confidential data. Synthetic results are test fixtures, hashes prove integrity rather than authenticity, and bounded survival is not evidence of future profitability. The optional remote-compute tool has side effects (backtest submission, never trading) and must not be retried automatically.

## Support

- **Team / builder:** Shahadat Islam / SKLab Studio; GitHub submission account `@ShahadatTest`
- **Contact:** https://github.com/ShahadatTest
- **License / rights:** First-party source is submitted under the program review and archive authorization in `RIGHTS.md`; no broader open-source license is asserted. Third-party dependencies and services remain under their own terms.
