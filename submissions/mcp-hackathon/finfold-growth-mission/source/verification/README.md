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

The current production evidence is [`benchmark-2026-09-03.json`](benchmark-2026-09-03.json): 20/20 successful calls, 100% first-attempt success, 16,897 ms p50, 22,548 ms p95, 24,206 ms p99, and all five platforms at 4/4. Tracking URLs were normalized before content-diversity counting; the conservative lower bound is 12 distinct validated assets. No latency sample was removed.

The earlier [`benchmark-2026-09-02.json`](benchmark-2026-09-02.json) remains committed as historical evidence rather than being overwritten: 19/20 successful calls and 14,394 ms p95, including the disclosed timeout.

## Reviewable live artifacts

- [`live-mission-2026-09-03.json`](live-mission-2026-09-03.json) is a real production LinkedIn result with only mission, tracking, and request identifiers redacted. It demonstrates a model-selected hypothesis, two canonical evidence excerpts, two exact claim mappings, and no fabricated outcome.
- [`live-mcp-tools-2026-09-03.json`](live-mcp-tools-2026-09-03.json) records the selected fields from an authenticated production `tools/list` response, including read-only/mutation, idempotency, and open-world annotations.
