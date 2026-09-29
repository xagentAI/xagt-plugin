# Verification

Everything here runs against the live service with **no credentials**. Copy, paste, compare.

```bash
API=https://regimen-nu.vercel.app
```

## 1. Health check and build binding

```bash
curl --fail --silent --show-error "$API/api/health"
```

Expected — `commit` is the 40-character SHA this deployment was built from:

```json
{"status":"ok","commit":"<40-character commit>","service":"regimen","slug":"rayyer-regimen","uptimeSeconds":0}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error "$API/.well-known/xagent-verification.json"
```

```json
{"schemaVersion":1,"slug":"rayyer-regimen","commit":"<the same 40-character commit>"}
```

**The two must agree, and they cannot drift.** Neither value is written by hand: both are
read from the platform's build metadata at request time, so whatever commit was built is
what both endpoints report. To confirm they match:

```bash
H=$(curl -s "$API/api/health" | sed -n 's/.*"commit":"\([0-9a-f]\{40\}\)".*/\1/p')
P=$(curl -s "$API/.well-known/xagent-verification.json" | sed -n 's/.*"commit":"\([0-9a-f]\{40\}\)".*/\1/p')
[ -n "$H" ] && [ "$H" = "$P" ] && echo "MATCH $H" || echo "MISMATCH health=$H proof=$P"
```

That commit resolves publicly at `https://github.com/RaYYeR220/regimen/commit/<commit>`.

## 3. The capability — a record that looks good and is not

This is the whole product in one call. The curve below has an **annualised Sharpe of 3.72**,
the kind of number a dashboard leads with.

```bash
curl --fail --silent --show-error -X POST "$API/api/v1/evaluate"   -H 'content-type: application/json'   -d '{"selector":{"source":"inline","trackRecord":{"label":"verification","equity":[
  {"t":"2026-06-01","equity":9988.82},{"t":"2026-06-02","equity":10130.95},{"t":"2026-06-03","equity":10125.66},
  {"t":"2026-06-04","equity":10102.36},{"t":"2026-06-05","equity":9954.86},{"t":"2026-06-06","equity":9952.21},
  {"t":"2026-06-07","equity":10213.34},{"t":"2026-06-08","equity":10340.84},{"t":"2026-06-09","equity":10596.64},
  {"t":"2026-06-10","equity":10691.78},{"t":"2026-06-11","equity":10818.96},{"t":"2026-06-12","equity":10902.34},
  {"t":"2026-06-13","equity":10582.67},{"t":"2026-06-14","equity":10806.02},{"t":"2026-06-15","equity":10958.68},
  {"t":"2026-06-16","equity":11111.84},{"t":"2026-06-17","equity":10780.41},{"t":"2026-06-18","equity":10447.53},
  {"t":"2026-06-19","equity":10303.44},{"t":"2026-06-20","equity":10248.17},{"t":"2026-06-21","equity":10351.77},
  {"t":"2026-06-22","equity":10383.67},{"t":"2026-06-23","equity":10533.4},{"t":"2026-06-24","equity":10440.23},
  {"t":"2026-06-25","equity":10546.45},{"t":"2026-06-26","equity":10671.78},{"t":"2026-06-27","equity":10573.36},
  {"t":"2026-06-28","equity":10978.85},{"t":"2026-06-29","equity":11144.98},{"t":"2026-06-30","equity":11456.38},
  {"t":"2026-07-01","equity":11360.07},{"t":"2026-07-02","equity":11237.49},{"t":"2026-07-03","equity":11205.11},
  {"t":"2026-07-04","equity":11226.08},{"t":"2026-07-05","equity":11412.9},{"t":"2026-07-06","equity":11515.26},
  {"t":"2026-07-07","equity":11458.29},{"t":"2026-07-08","equity":11284.84},{"t":"2026-07-09","equity":11212.48},
  {"t":"2026-07-10","equity":11531.12},{"t":"2026-07-11","equity":11390.91},{"t":"2026-07-12","equity":11492.24},
  {"t":"2026-07-13","equity":11636.24},{"t":"2026-07-14","equity":11336.09},{"t":"2026-07-15","equity":11392.42},
  {"t":"2026-07-16","equity":11735.62},{"t":"2026-07-17","equity":11309.76},{"t":"2026-07-18","equity":11282.26},
  {"t":"2026-07-19","equity":11303.44},{"t":"2026-07-20","equity":11163.89},{"t":"2026-07-21","equity":11319.61},
  {"t":"2026-07-22","equity":11350.78},{"t":"2026-07-23","equity":11063.69},{"t":"2026-07-24","equity":11291.12},
  {"t":"2026-07-25","equity":11487.44},{"t":"2026-07-26","equity":11750.69},{"t":"2026-07-27","equity":12136.26},
  {"t":"2026-07-28","equity":12272.73},{"t":"2026-07-29","equity":12351.09},{"t":"2026-07-30","equity":12079.58}]}}}'
```

Expected, in `data.report`:

| Field | Value |
|---|---|
| `performance.sharpeAnnualised` | `3.72` |
| `evidence.tier` | **`weak`** |
| `evidence.probabilisticSharpe` | `0.9231` |
| `evidence.sharpeConfidenceInterval` | `lower: -0.0332`, `upper: 0.4624` — **zero is inside** |
| `evidence.minimumTrackRecordLength` | `78.1` |
| `evidence.periodsShortOfSignificance` | `20` |
| `sample.usableReturns` | `59` |

Read that together: a Sharpe ratio above three, and the evidence still cannot rule out that
the true Sharpe is zero. `evidence.rationale` says so in sentences. These values are
deterministic — the bootstrap is seeded — so they reproduce exactly on every call.

## 4. The refusal — the behaviour that matters most

A record too short to say anything about must produce no number at all.

```bash
curl --silent -X POST "$API/api/v1/evaluate"   -H 'content-type: application/json'   -d '{"selector":{"source":"inline","trackRecord":{"label":"too-short","equity":[
  {"t":"2026-06-01","equity":10000},{"t":"2026-06-02","equity":10500},{"t":"2026-06-03","equity":11000}]}}}'
```

Expected: HTTP 200, `data.report.evidence.tier` = `insufficient_evidence`, and
`data.report.evidence.probabilisticSharpe` = `null`. No Sharpe ratio is reported, because
none would mean anything.

## 5. Regimen attacking its own verdict

Same curve as section 3, with the controls turned on:

```bash
curl --fail --silent --show-error -X POST "$API/api/v1/self-attack"   -H 'content-type: application/json'   -d '{"selector":{"source":"inline","trackRecord":{"label":"verification","equity":[
  {"t":"2026-06-01","equity":9988.82},{"t":"2026-06-02","equity":10130.95},{"t":"2026-06-03","equity":10125.66},
  {"t":"2026-06-04","equity":10102.36},{"t":"2026-06-05","equity":9954.86},{"t":"2026-06-06","equity":9952.21},
  {"t":"2026-06-07","equity":10213.34},{"t":"2026-06-08","equity":10340.84},{"t":"2026-06-09","equity":10596.64},
  {"t":"2026-06-10","equity":10691.78},{"t":"2026-06-11","equity":10818.96},{"t":"2026-06-12","equity":10902.34},
  {"t":"2026-06-13","equity":10582.67},{"t":"2026-06-14","equity":10806.02},{"t":"2026-06-15","equity":10958.68},
  {"t":"2026-06-16","equity":11111.84},{"t":"2026-06-17","equity":10780.41},{"t":"2026-06-18","equity":10447.53},
  {"t":"2026-06-19","equity":10303.44},{"t":"2026-06-20","equity":10248.17},{"t":"2026-06-21","equity":10351.77},
  {"t":"2026-06-22","equity":10383.67},{"t":"2026-06-23","equity":10533.4},{"t":"2026-06-24","equity":10440.23},
  {"t":"2026-06-25","equity":10546.45},{"t":"2026-06-26","equity":10671.78},{"t":"2026-06-27","equity":10573.36},
  {"t":"2026-06-28","equity":10978.85},{"t":"2026-06-29","equity":11144.98},{"t":"2026-06-30","equity":11456.38},
  {"t":"2026-07-01","equity":11360.07},{"t":"2026-07-02","equity":11237.49},{"t":"2026-07-03","equity":11205.11},
  {"t":"2026-07-04","equity":11226.08},{"t":"2026-07-05","equity":11412.9},{"t":"2026-07-06","equity":11515.26},
  {"t":"2026-07-07","equity":11458.29},{"t":"2026-07-08","equity":11284.84},{"t":"2026-07-09","equity":11212.48},
  {"t":"2026-07-10","equity":11531.12},{"t":"2026-07-11","equity":11390.91},{"t":"2026-07-12","equity":11492.24},
  {"t":"2026-07-13","equity":11636.24},{"t":"2026-07-14","equity":11336.09},{"t":"2026-07-15","equity":11392.42},
  {"t":"2026-07-16","equity":11735.62},{"t":"2026-07-17","equity":11309.76},{"t":"2026-07-18","equity":11282.26},
  {"t":"2026-07-19","equity":11303.44},{"t":"2026-07-20","equity":11163.89},{"t":"2026-07-21","equity":11319.61},
  {"t":"2026-07-22","equity":11350.78},{"t":"2026-07-23","equity":11063.69},{"t":"2026-07-24","equity":11291.12},
  {"t":"2026-07-25","equity":11487.44},{"t":"2026-07-26","equity":11750.69},{"t":"2026-07-27","equity":12136.26},
  {"t":"2026-07-28","equity":12272.73},{"t":"2026-07-29","equity":12351.09},{"t":"2026-07-30","equity":12079.58}]}},"options":{"simulations":500}}'
```

Expected, in `data.report`:

- `verdict` = `engine_sane`.
- `controls[0].passed` = `true`, `controls[0].observed` = `0.5` — the same returns with their
  mean removed grade at exactly 50% confidence, which is the correct answer for a series
  with no edge. Had this failed, the verdict in section 3 would not be trustworthy and the
  response says so.
- `nullDistribution.empiricalPValue` = `0.0679` — **6.8% of simulated strategies with no edge
  at all, matched for length and volatility, score at least as well as this one.**
- `nullDistribution.nullMedianPsr` = `0.492`, `nullP95Psr` = `0.935`.

## 6. Error behaviour

Malformed body:

```bash
curl --silent -o /dev/null -w '%{http_code}\n' -X POST "$API/api/v1/evaluate" \
  -H 'content-type: application/json' -d '{"selector":{"source":"inline"}}'
```

Expected `400`, with `error.code` = `invalid_input`, `error.retryable` = `false`, and
`error.details.issues` naming the missing field path.

Nexus source with no key on a deployment that has no demo key:

```bash
curl --silent -o /dev/null -w '%{http_code}\n' -X POST "$API/api/v1/evaluate" \
  -H 'content-type: application/json' -d '{"selector":{"source":"olaxbt-nexus"}}'
```

Expected `401` with `error.code` = `missing_credentials` and a `remedy` naming the header
to send. If the deployment does have a demo key configured, this returns `200` instead and
`meta.mode` is `demo`; `GET /api/v1/status` reports which case applies.

Rejected cross-origin request:

```bash
curl --silent -o /dev/null -w '%{http_code}\n' -H 'Origin: https://evil.example' "$API/api/v1/status"
```

Expected `403`.

## 7. The MCP endpoint

```bash
curl --fail --silent --show-error -X POST "$API/mcp" \
  -H 'content-type: application/json' \
  -H 'accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2026-07-28' \
  -H 'Mcp-Method: tools/list' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{"_meta":{
       "io.modelcontextprotocol/protocolVersion":"2026-07-28",
       "io.modelcontextprotocol/clientInfo":{"name":"verification","version":"1.0.0"},
       "io.modelcontextprotocol/clientCapabilities":{}}}}'
```

Expected: four tools, each with an `outputSchema` and `annotations.readOnlyHint: true`;
`result.resultType` = `"complete"`; `result.ttlMs` and `result.cacheScope` present as the
2026-07-28 revision requires; `_meta["io.modelcontextprotocol/serverInfo"]` naming the server.

```bash
curl --silent -o /dev/null -w '%{http_code}\n' "$API/mcp"
```

Expected `405` — the current revision defines a single POST endpoint, and refusing GET is
how a client distinguishes this from a legacy HTTP+SSE server.

## 8. Reproducing the analysis locally

```bash
git clone https://github.com/RaYYeR220/regimen && cd regimen
pnpm install
pnpm test        # statistics and evaluation suites
pnpm typecheck
pnpm eval        # regenerates EVAL.md byte-for-byte
pnpm dev         # the same API on http://localhost:3000
```

Every seeded computation — bootstrap intervals, permutation p-values, null distributions,
the whole evaluation — reproduces exactly. `pnpm eval` rewrites `EVAL.md` and
`eval-results.json`; `git diff` on them should be empty.

No secrets are required for any of the above.
