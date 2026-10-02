# Verification evidence

## Review-window refresh — 2026-09-30

The service was redeployed during the official review window (September 20–October 1) with a new public review commit and refreshed live evidence:

- New public credential-free demo route `GET /v1/demo/mission` (hourly rotation across all five platforms, isolated never-issued demo key, last-good fallback, typed errors).
- Fresh five-platform 20-call benchmark: 20/20 successes, 95% first-attempt success (one call used the single allowed repair), 10,354 ms p50, 18,280 ms p95, 20,098 ms p99, at least 14 distinct validated assets.
- The 2026-09-30 live mission, MCP discovery, and demo captures are committed under `source/verification/`. They were captured under code-identical parent commit `02be14a556692b1c445da03bce4ec9a2ca59d41e` before the documentation-only final commit; each artifact records its exact capture commit.
- The test suite grew from 56 to 65 Worker-runtime tests covering the demo route (fresh generation, hourly uniqueness, key isolation, public click attribution, method guard, last-good fallback, typed cold failure, concurrent warm-up, cron warm-up).

## Validation refresh — 2026-09-07

The submission branch now includes official base commit `a9f5526` so a fresh PR event can use the repaired validation workflow. Attempt 2 of run `33752945312` stopped before inspecting this submission: the workflow checked out old base commit `fc76acc206bbefeaf846d30206656e2c87558785`, which does not contain `scripts/submission-lifecycle.mjs`, and Node exited with `MODULE_NOT_FOUND`.

The current official offline validator passes. The current online validator also passes against the unchanged source commit and live endpoints below. For this local online check, DNS was resolved through Google's public DNS-over-HTTPS service because the workstation proxy returns a reserved `198.18.x.x` address; the validator's public-IP checks, pinned HTTPS requests, certificate verification, and exact commit comparisons remained enabled. This local result is separate from the fresh GitHub Actions result.

## Prerequisites

- Review commit: `cfc413d1e6ae81e96a6f42f9648dd84b3a370df9`
- API base URL: `https://api.finfold.app`
- Authentication: obtain the short-lived Bearer review key through the program's approved private review channel and export it as `REVIEW_KEY`. It is not present in this repository.

## 1. Health check

```bash
curl --fail --silent --show-error https://api.finfold.app/health
```

Expected response:

```json
{"status":"ok","commit":"cfc413d1e6ae81e96a6f42f9648dd84b3a370df9"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://api.finfold.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"finfold-growth-mission","commit":"cfc413d1e6ae81e96a6f42f9648dd84b3a370df9"}
```

## 3. Public demo (no credential)

```bash
curl --fail --silent --show-error https://api.finfold.app/v1/demo/mission
```

Expected HTTP `200` wraps a real mission in `demo` metadata: `fresh: true`, hourly `generatedForHour`/`nextRefreshAt`, the five-platform rotation, and the same `mission`/`asset`/`evidence`/`claimMap`/`validation`/`tracking`/`attribution`/`outcome` shape as the authenticated routes. Opening its `https://api.finfold.app/r/...` CTA records a real anonymous click that later reads show in `attribution.clicks`. A capture with one real click counted is committed at `source/verification/live-demo-2026-09-30.json`.

## 4. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://api.finfold.app/v1/missions \
  --header "authorization: Bearer ${REVIEW_KEY}" \
  --header "content-type: application/json" \
  --header "idempotency-key: reviewer-$(date +%s)-$RANDOM" \
  --data '{"sourceUrl":"https://www.finfold.app/en","objective":"leads","platform":"linkedin","locale":"en"}'
```

Expected HTTP `201` contains exactly one `mission`, one `asset` with an `https://api.finfold.app/r/...` CTA, canonical `evidence`, a `claimMap`, `validation.passed: true`, `sideEffects.published: false`, and provenance bound to the review commit. Every `claimMap.claim` must occur verbatim in the asset and its cited evidence quote. The compiler preserves the model-selected angle and audience, can combine up to three excerpts, and uses distinct structures for all five explicit platforms. A redacted real response is committed at `source/verification/live-mission-2026-09-30.json` (and the 2026-09-03 capture remains).

Do not submit a fabricated lead, signup, purchase, or revenue event. If a real attributable outcome occurs, use the documented outcome endpoint and a unique source-system `eventId`.

## 5. MCP discovery

```bash
curl --fail --silent --show-error \
  --request POST https://api.finfold.app/mcp \
  --header "authorization: Bearer ${REVIEW_KEY}" \
  --header "content-type: application/json" \
  --data '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

Expected tool names:

- `finfold_create_growth_mission`
- `finfold_get_growth_mission`
- `finfold_record_growth_outcome`

The create and outcome tools declare mutation and idempotency semantics; the get tool declares read-only behavior. Selected fields from the authenticated live response are committed at `source/verification/live-mcp-tools-2026-09-30.json` (and the 2026-09-03 capture remains). The test suite also executes the complete MCP create → read → outcome → read sequence.

## 6. Tracking redirect

Export the tracking URL returned by mission creation as `TRACKING_URL`. Open it without following redirects and verify a `302` to the stored destination with `utm_source=finfold_growth_mission`, the requested platform in `utm_medium`, and the returned mission ID in `utm_campaign`:

```bash
curl --silent --show-error --dump-header - --output /dev/null "${TRACKING_URL}"
```

The production verification recorded one real test click and read back `clicks: 1`, zero conversion outcomes, and `verdict: running`; no fake outcome was written.

## 7. Safe failure

Calling an authenticated route without a Bearer key fails before any source fetch or model call:

```bash
curl --silent --show-error \
  --request POST https://api.finfold.app/v1/missions \
  --header "content-type: application/json" \
  --header "idempotency-key: missing-auth-0001" \
  --data '{"sourceUrl":"https://www.finfold.app/en","objective":"leads","platform":"linkedin","locale":"en"}'
```

Expected HTTP `401` with error code `AUTH_REQUIRED`. Source-safety and generation failures similarly return typed errors and never return partial content.

## 8. Production gate

The current credential-free report is the in-window 2026-09-30 re-run at `source/verification/benchmark-2026-09-30.json`: 20 sequential calls across LinkedIn, X, Reddit, Xiaohongshu, and WeChat; 20/20 successes; 95% first-attempt success (one call used the single allowed repair); 10,354 ms p50; 18,280 ms p95; 20,098 ms p99; at least 14 distinct validated assets after tracking-URL normalization; no latency sample removed. The 2026-09-03 report (20/20, 100% first-attempt, 16,897 ms p50, every platform 4/4, lower bound 12 distinct assets) remains committed at `source/verification/benchmark-2026-09-03.json`.

The prior `source/verification/benchmark-2026-09-02.json` remains in the package as historical evidence, including its disclosed timeout; it is not presented as the current production result.

## 9. Additional safety checks

The 65-test Worker-runtime suite now also covers same-site HTTPS tracking destinations, IPv4-mapped IPv6 and multicast blocking, measurement-window enforcement, single-currency revenue verdicts, anonymous-click-only `inconclusive`, browser preflight, public `HEAD`, five platform-native structures, and the complete MCP outcome loop.
