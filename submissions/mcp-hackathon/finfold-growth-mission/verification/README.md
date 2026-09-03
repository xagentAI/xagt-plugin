# Verification evidence

## Prerequisites

- Review commit: `65a4a545ca74b0e357973de433fd108c375531bc`
- API base URL: `https://api.finfold.app`
- Authentication: obtain the short-lived Bearer review key through the program's approved private review channel and export it as `REVIEW_KEY`. It is not present in this repository.

## 1. Health check

```bash
curl --fail --silent --show-error https://api.finfold.app/health
```

Expected response:

```json
{"status":"ok","commit":"65a4a545ca74b0e357973de433fd108c375531bc"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://api.finfold.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"finfold-growth-mission","commit":"65a4a545ca74b0e357973de433fd108c375531bc"}
```

## 3. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://api.finfold.app/v1/missions \
  --header "authorization: Bearer ${REVIEW_KEY}" \
  --header "content-type: application/json" \
  --header "idempotency-key: reviewer-$(date +%s)-$RANDOM" \
  --data '{"sourceUrl":"https://www.finfold.app/en","objective":"leads","platform":"linkedin","locale":"en"}'
```

Expected HTTP `201` contains exactly one `mission`, one `asset` with an `https://api.finfold.app/r/...` CTA, canonical `evidence`, a `claimMap`, `validation.passed: true`, `sideEffects.published: false`, and provenance bound to the review commit. Every `claimMap.claim` must occur verbatim in the asset and its cited evidence quote. The compiler preserves the model-selected angle and audience, can combine up to three excerpts, and uses distinct structures for all five explicit platforms. A redacted real response is committed at `source/verification/live-mission-2026-09-03.json`.

Do not submit a fabricated lead, signup, purchase, or revenue event. If a real attributable outcome occurs, use the documented outcome endpoint and a unique source-system `eventId`.

## 4. MCP discovery

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

The create and outcome tools declare mutation and idempotency semantics; the get tool declares read-only behavior. Selected fields from the authenticated live response are committed at `source/verification/live-mcp-tools-2026-09-03.json`. The test suite also executes the complete MCP create → read → outcome → read sequence.

## 5. Tracking redirect

Export the tracking URL returned by mission creation as `TRACKING_URL`. Open it without following redirects and verify a `302` to the stored destination with `utm_source=finfold_growth_mission`, the requested platform in `utm_medium`, and the returned mission ID in `utm_campaign`:

```bash
curl --silent --show-error --dump-header - --output /dev/null "${TRACKING_URL}"
```

The production verification recorded one real test click and read back `clicks: 1`, zero conversion outcomes, and `verdict: running`; no fake outcome was written.

## 6. Safe failure

Calling an authenticated route without a Bearer key fails before any source fetch or model call:

```bash
curl --silent --show-error \
  --request POST https://api.finfold.app/v1/missions \
  --header "content-type: application/json" \
  --header "idempotency-key: missing-auth-0001" \
  --data '{"sourceUrl":"https://www.finfold.app/en","objective":"leads","platform":"linkedin","locale":"en"}'
```

Expected HTTP `401` with error code `AUTH_REQUIRED`. Source-safety and generation failures similarly return typed errors and never return partial content.

## 7. Production gate

The current credential-free report is included at `source/verification/benchmark-2026-09-03.json`: 20 sequential calls across LinkedIn, X, Reddit, Xiaohongshu, and WeChat; 20/20 successes; 100% first-attempt success; 16,897 ms p50; 22,548 ms p95; 24,206 ms p99; every platform 4/4. Tracking URLs were normalized before content-diversity counting, producing a conservative lower bound of 12 distinct validated assets. No latency sample was removed.

The prior `source/verification/benchmark-2026-09-02.json` remains in the package as historical evidence, including its disclosed timeout; it is not presented as the current production result.

## 8. Additional safety checks

The 56-test Worker-runtime suite now also covers same-site HTTPS tracking destinations, IPv4-mapped IPv6 and multicast blocking, measurement-window enforcement, single-currency revenue verdicts, anonymous-click-only `inconclusive`, browser preflight, public `HEAD`, five platform-native structures, and the complete MCP outcome loop.
