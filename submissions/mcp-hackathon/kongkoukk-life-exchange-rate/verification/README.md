# Verification evidence

## Prerequisites

- **Public source:** https://github.com/KongkouKK/life-exchange-rate-mcp
- **Review commit:** `238954196ea6922d3cea2ae8acb914b0f4e01dbb`
- **API base URL:** https://life-exchange-rate-mcp.vercel.app
- **Authentication:** None; no review credential is needed.
- Capability fixture commands below run from the complete runnable project at `source/` in the submission root. If starting in this `verification/` directory, enter `../source` first.

## 1. Health check

```bash
curl --fail --silent --show-error --max-time 60 https://life-exchange-rate-mcp.vercel.app/health
```

Expected response:

```json
{"status":"ok","version":"0.2.0","commit":"238954196ea6922d3cea2ae8acb914b0f4e01dbb","mcp":"enabled"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error --max-time 60 https://life-exchange-rate-mcp.vercel.app/.well-known/xagent-verification.json
```

Required fields in the response:

```json
{"schemaVersion":1,"slug":"kongkoukk-life-exchange-rate","commit":"238954196ea6922d3cea2ae8acb914b0f4e01dbb"}
```

The full response also reports version and production-origin health/OpenAPI/MCP URLs. Check these refer to `https://life-exchange-rate-mcp.vercel.app` and retain the canonical `/mcp/` trailing slash. Do not add a redirect-following option.

## 3. Capability call and safe failure

Run from the runnable project directory:

```bash
curl --fail --silent --show-error --max-time 60 \
  https://life-exchange-rate-mcp.vercel.app/v1/translate \
  --header 'Content-Type: application/json' \
  --data-binary @verification/fixtures/fx-request.json

curl --silent --show-error --max-time 60 --write-out '\nHTTP %{http_code}\n' \
  https://life-exchange-rate-mcp.vercel.app/v1/translate \
  --header 'Content-Type: application/json' \
  --data-binary @verification/fixtures/invalid-request.json
```

The valid fixture expects HTTP 200 with `direct_effect_home: 1739.13`, `home_currency: SEK`, `work_hours_equivalent: 8.7`, calculation trace and synthetic event provenance. The invalid fixture expects HTTP 422 with validation details. Use `curl.exe` on Windows PowerShell when necessary. The fixture contains synthetic household values.

The [public REST record](hosted-rest-verification-final.json), captured at 2026-09-16 10:00:54 UTC, confirms those results using published fixture files and the same review commit before and after the calls. Provider failures in strict live mode return sanitized HTTP 502 errors. A policy/energy fallback is labeled as synthetic and is not a live-provider success.

## 4. MCP and live-provider checks

Connect a real MCP client to `https://life-exchange-rate-mcp.vercel.app/mcp/`; a browser GET does not exercise tools.

The [complete hosted record](hosted-live-verification-final.json), captured at 2026-09-16 09:55:43 UTC, passed all nine tools in current protocol `2026-07-28` and legacy protocol `2025-11-25`. Each mode passed 12 positive calls and rejected 7 invalid-input cases. FX and Fed RSS were live. Policy and energy were labeled synthetic fixtures; no live EIA validation is claimed. The separately fetched headline is not presented as the cause of the FX change.

The [additional deterministic record](hosted-verification-final.json) verifies health/proof binding, tool listing, fixture computation and invalid-input behavior. The [source comparison record](source-verification-final.json) verifies the public 76-file archive for the exact commit, allowing text line-ending differences only. Original dependency notices and applicable source terms are retained under [licenses](licenses/DEPENDENCIES.md).

## 5. Official package validation

From a clean official-repository checkout, execute before publishing:

```bash
npm ci
npm run validate:submission -- --dir submissions/mcp-hackathon/kongkoukk-life-exchange-rate
npm run validate:submission -- --dir submissions/mcp-hackathon/kongkoukk-life-exchange-rate --online
```

Both official commands passed on **2026-09-17 at 07:03 UTC**. The [archived validation record](official-validation.json) retains the actual command lines, start/end timestamps, exit codes, original stdout/stderr, parsed results and the SHA-256 of the unmodified official validator. Offline validation confirmed the manifest, 73 source files, baseline secret scan and repeatable verification instructions. Online validation additionally verified the public source commit, healthy deployed API bound to that commit, and standard deployment proof. TLS verification was unchanged.

The inspected official validator uses a 60-second request timeout, no redirects/retries and a 64 KiB response cap. The archived record captures the checks immediately before adding that record and this summary. After adding them, both commands are run again on the complete package; that final output is retained outside the submission package to avoid a self-referential evidence update. Final diff review must remain limited to this one submission directory. Passing these checks does not establish a security certification, program acceptance or award.
