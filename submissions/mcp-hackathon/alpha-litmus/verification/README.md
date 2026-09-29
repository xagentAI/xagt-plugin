# AlphaLitmus verification evidence

**Track:** OlaXBT × X-Agent Trading Challenge

## Prerequisites

- Review commit: `00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f`
- API base URL: `https://alphalitmus.sklab.cc`
- Authentication: None for the public review routes. The live route is locked to fixed Candidate v1; arbitrary Nexus reads and remote compute remain disabled.
- Tool: `curl`

The built-in demo uses synthetic data and must remain `UNPROVEN`; it is a repeatable capability exercise, not a profitable-strategy claim.

## 1. Health check

```bash
curl --fail --silent --show-error https://alphalitmus.sklab.cc/health
```

Expected response:

```json
{"commit":"00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f","commit_reviewable":true,"status":"ok","service":"alpha-litmus","no_execution":true,"provenance_basis":"syntax_only_not_authenticated"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://alphalitmus.sklab.cc/.well-known/xagent-verification.json
```

Expected response:

```json
{"commit":"00140a38fb4d7ec0da1f896d7f873bcc6b23aa0f","commit_reviewable":true,"schemaVersion":1,"slug":"alpha-litmus","provenance_basis":"syntax_only_not_authenticated"}
```

## 3. Real capability call

Run the agent-facing release gate against the deployed service. It executes the
complete bounded mixed-failure challenge, verifies the source certificate, and
returns the decision contract plus the authoritative report:

```bash
curl --fail --silent --show-error https://alphalitmus.sklab.cc/v1/release-gate/demo/mixed
```

Verify these invariants rather than a creation timestamp:

- `schema_version` is `alphalitmus-release-gate-1`;
- `decision` is `INSUFFICIENT_EVIDENCE` and `recommended_action` is `COLLECT_MORE_EVIDENCE`;
- `source_verdict` is `UNPROVEN` and `evidence_classification` is `synthetic_reference`;
- `source_report_verified` and `no_execution` are exactly `true`, while `profitability_claimed` is `false`;
- `report_id` equals `canonical_report_hash`;
- the embedded `report.observed_failures` contains six entries for the current fixture;
- the embedded `report.provenance.commit` equals the review commit and `commit_reviewable` is `true`.

The dashboard at `https://alphalitmus.sklab.cc/` calls the same endpoint and renders the verdict, folds, cost frontier, parameter sensitivity, certificate, and limitations.

## 4. Recorded Nexus evidence replay

```bash
curl --fail --silent --show-error https://alphalitmus.sklab.cc/v1/nexus/replay/candidate-v1
```

Verify these invariants:

- `snapshot_id` is `candidate-v1`, and the aggregate snapshot SHA-256 is `3a086a1cbf392d15ae961227c091afa343fde5f21b3aebc2aa81ff9d33b389f8`;
- the four evidence surfaces are `signal`, `metrics`, `equity`, and `trades`;
- `historical` and `no_execution` are exactly `true`; `live` and `profitability_claimed` are exactly `false`;
- the release gate is `INCONSISTENT`, `BLOCK_DEPLOYMENT`, and `DO_NOT_DEPLOY` with exact-true `source_report_verified`;
- `TRADE_SYMBOLS` is a `MISMATCH` because recent trades include a symbol outside the requested strategy symbol;
- the disclosure says this is recorded historical evidence, not a live call, independent source authentication, or future-profit evidence.

This route uses no Nexus key and performs no live Nexus request. Hashes establish source-commit-bound content consistency, not authorship or source authenticity.

## 5. Live Nexus pulse

```bash
curl --fail --silent --show-error https://alphalitmus.sklab.cc/v1/nexus/live/candidate-v1
```

Verify these invariants:

- `live_schema_version` is `alphalitmus-live-nexus-1`, strategy ID is `str_b840280ce037`, and symbol is `BTC/USDT`;
- the four surfaces are `signal`, `metrics`, `equity`, and `trades`, with per-surface fetch times and freshness;
- `live` and `no_execution` are exactly `true`; `historical`, `profitability_claimed`, and `recorded_fallback_used` are exactly `false`;
- `release_gate.source_report_verified` is exactly `true`;
- the current observed decision is `INCONSISTENT`, `BLOCK_DEPLOYMENT`, `DO_NOT_DEPLOY`;
- repeat calls may return `cache_status: hit` with cache age and the 60-second TTL disclosed.

The endpoint accepts no body, query parameters, strategy ID, or symbol. Upstream failure returns a bounded `LIVE_NEXUS_*` error and never substitutes the recorded snapshot.

## 6. Safe invalid-input behavior

```bash
curl --silent --show-error --include \
  --request POST https://alphalitmus.sklab.cc/v1/release-gate \
  --header 'content-type: application/json' \
  --data '{}'
```

Expected status is HTTP 422 and the bounded response is:

```json
{"detail":"INVALID_REQUEST"}
```

The error does not echo the invalid body or expose an exception trace. A valid Nexus-mode request while public Nexus access is disabled returns an evidence-labelled unavailable result rather than making an outbound call or treating missing evidence as success.

## 7. Independent local replay

From the submitted `source/` directory, install the review environment and run all gates:

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
python -m ruff check .
python -m mypy app
python -m tools.local_smoke
```

The recorded reviewed-source results are 680 passing tests with zero failures and zero skips, Ruff clean, strict mypy clean across 18 source files, and a successful local smoke test discovering all eight MCP tools. Run the commands again in the review environment rather than treating these recorded counts as current execution evidence.
