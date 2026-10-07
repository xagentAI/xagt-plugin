# Verification procedure

## Offline gates

From the exact public commit:

```bash
npm ci
npm run check
```

Expected gates: lint, strict TypeScript, all Worker-runtime tests, Wrangler dry-run bundle, and secret scan all pass. Tests use a local D1 database and intercepted source/model responses; they do not need a paid model key.

## Live commit proof

```bash
node scripts/verify-deployment.mjs <40-character-public-commit>
```

The script requires both `/health` and `/.well-known/xagent-verification.json` to return the same exact commit. It fails on any mismatch.

## Public credential-free demo

```bash
curl --fail --silent --show-error https://api.finfold.app/v1/demo/mission
```

No key required. The response wraps one real mission in `demo` metadata: `fresh`, hourly `generatedForHour`/`nextRefreshAt`, the five-platform rotation, and on fallback `fallback` plus `lastErrorCode`. Evidence for the live route, including one real anonymous click counted in `attribution.clicks`, is committed at [`live-demo-2026-09-30.json`](live-demo-2026-09-30.json).

## Real production loop

1. Create a mission from a real public page with a unique `Idempotency-Key`.
2. Confirm every evidence quote is a literal substring of the referenced public page section.
3. Open the returned `/r/{trackingCode}` and confirm a safe 302 to the stored destination with Finfold UTM fields.
4. Record one real outcome with a unique caller event ID.
5. Read the mission and confirm attribution, verdict, target, due time, and next action.
6. Replay both mutations and confirm the original response/duplicate semantics.

## Multi-platform production gate

Use a dedicated review key whose allowance has at least 20 remaining calls:

```bash
REVIEW_KEY="..." SOURCE_URL="https://www.finfold.app/en" \
  BENCHMARK_PLATFORMS="linkedin,x,reddit,xiaohongshu,wechat" npm run benchmark
```

The script writes a credential-free JSON report under ignored `benchmark-results/`. It reports p50/p95/p99, first-attempt success, evidence count, asset length, and the number of unique validated assets after normalizing each tracking URL. It exits non-zero unless at least 95% of calls succeed and synchronous p95 is at most 30 seconds, and separately reports whether the 98% winning target passed. If the synchronous gate fails, the release must change mission creation to `202 Accepted` plus polling before submission; the synchronous claim must not be published.

The current production evidence is [`benchmark-2026-09-30.json`](benchmark-2026-09-30.json), re-run during the official review window against commit `02be14a556692b1c445da03bce4ec9a2ca59d41e`: 20/20 successful calls, 95% first-attempt success (one call used the single allowed repair), 10,354 ms p50, 18,280 ms p95, 20,098 ms p99, at least 14 distinct validated assets after tracking-URL normalization, and both the synchronous and winning-target gates passed. No latency sample was removed. The prior [`benchmark-2026-09-03.json`](benchmark-2026-09-03.json) remains committed: 20/20 calls, 16,897 ms p50, 22,548 ms p95, all five platforms 4/4.

The earlier [`benchmark-2026-09-02.json`](benchmark-2026-09-02.json) remains committed as historical evidence rather than being overwritten: 19/20 successful calls and 14,394 ms p95, including the disclosed timeout.

## Reviewable live artifacts

- [`live-mission-2026-09-30.json`](live-mission-2026-09-30.json) is a real production LinkedIn result captured during the review window against the current commit, with only mission, tracking, and request identifiers redacted. It demonstrates a model-selected hypothesis, two canonical evidence excerpts, exact claim mappings, and no fabricated outcome.
- [`live-mcp-tools-2026-09-30.json`](live-mcp-tools-2026-09-30.json) records the selected fields from an authenticated production `tools/list` response, including read-only/mutation, idempotency, and open-world annotations.
- [`live-demo-2026-09-30.json`](live-demo-2026-09-30.json) records the credential-free public demo route response, including one real anonymous click already counted in `attribution.clicks`.
- The 2026-09-03 live artifacts remain committed as historical evidence and are superseded by the 2026-09-30 captures above.
