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

## 20-call production gate

Use a dedicated review key whose allowance has at least 20 remaining calls:

```bash
REVIEW_KEY="..." SOURCE_URL="https://www.finfold.app/" npm run benchmark
```

The script writes a credential-free JSON report under ignored `benchmark-results/`. It exits non-zero unless at least 19 of 20 calls succeed and synchronous p95 is at most 30 seconds. If this gate fails, the release must change mission creation to `202 Accepted` plus polling before submission; the synchronous claim must not be published.

The committed production run is [`benchmark-2026-09-02.json`](benchmark-2026-09-02.json): 19/20 successful calls (95%), 14,394 ms p95, gate passed. Run 16 hit the client's 35-second timeout; it is retained in the report rather than excluded.
