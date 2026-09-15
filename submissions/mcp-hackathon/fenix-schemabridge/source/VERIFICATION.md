# Verification

## Readable developer links — 13 September 2026

The homepage developer links now target readable documentation at /docs and live status at /status. The JSON API index, health, deployment proof and OpenAPI paths remain available with their machine contracts. Documentation examples and links are checked against the implementation, and the status page must distinguish an actual successful health response from unavailable or unverified service state. Fresh link-by-link browser and public-source checks are recorded separately for the resulting deployed commit; earlier evidence is historical.

## Human-readable homepage — 13 September 2026

The root route serves an English HTML page with a live editable CSV example. The owner's language correction removes Russian copy and the language switch from the page and browser script. The machine-readable index remains at /v1. Two local asset routes serve CSS and JavaScript with a Content Security Policy that permits only same-origin scripts, styles and API requests; no inline scripts or third-party dependencies are required. The transformation implementation is unchanged. Fresh browser and deployment checks are recorded separately after publishing this reviewed revision; earlier HTTP counts below describe earlier revisions.

## Cloudflare migration — 13 September 2026

The deployment target is Cloudflare Workers at schemabridge.wiaikit.com. The build uses pinned Wrangler 4.131.1 in dry-run mode; the former hosting adapter and project manifest have been removed. The transformation and HTTP implementation are unchanged by this migration. Public checks for the new deployment are recorded separately with the resulting real Git SHA, Cloudflare version and timestamps; the historical local results below are not cloud-deployment evidence.

## Review update — 13 September 2026

An independent source audit reproduced an ambiguity in the integer-input documentation: JSON parsing can round a numeric literal before validation. README and OpenAPI now distinguish parsed IEEE-754 numbers from strict decimal strings. A raw-body regression covers five numeric spellings, their parsed values, unchanged-cell counts, and rejection of the equivalent strings. `node --test` passed **29 tests, 0 failures** after this correction. No transformation-runtime change was necessary.

The release also provides `GET /` and `GET /v1` service descriptions so the published base address is directly useful in a browser. Existing routing tests verify both descriptions, request limits, capability method/path, wrong-method refusal and the six documented routes.

Public-release HTTP results and final source/deployment reconciliation are recorded separately in the contest entry's `verification/README.md`; the historical checks below do not claim public availability.

## Earlier local verification

Verified on **12 September 2026**, on Windows with **Node.js v24.16.0**. The application has no external runtime dependencies.

| Check | Result |
|---|---|
| `node --test` | 28 passed; 0 failed, skipped or cancelled |
| `node tools/demo.mjs` | CSV and JSON fixtures: HTTP 200; invalid fixture: 422; unconfigured health: 503 |
| Official Wrangler 4.131.1, bundled local workerd | 29 HTTP smoke checks passed; 0 failed |

## Behavior coverage

The Node suite covers all four conversion types, safe integer handling, null/missing/trim behavior, CSV quoting and line endings, malformed input, unknown options, record/field/string/body/output limits, streaming UTF-8 handling, bounded error details, request independence, methods and proof responses. It includes actual loopback HTTP through the development adapter.

The workerd checks used Wrangler's local runtime and bundling, with remote bindings disabled. They verified fixture results, unconfigured health/proof refusal, all four OpenAPI paths, quoted and malformed CSV, exact 32 KiB and oversized bodies, chunked requests, UTF-8 split across individual bytes, JSON/CSV limit boundaries, output amplification and HTTP errors. No core implementation change was needed for that runtime.

Health/proof responses with configured values were tested in the Node suite using explicitly synthetic test values. The local workerd run used no commit configuration and correctly returned 503. No real public commit or deployed proof was verified in that earlier local run.

## Reproduce

Run the first two commands from the project directory:

```text
node --test
node tools/demo.mjs
```

Start **Wrangler 4.131.1** using the loopback-only command in [README.md](README.md#test-in-the-local-workers-runtime), then run:

```text
node tools/workerd-smoke.mjs http://127.0.0.1:8789
```

The checked runtime used HTTP port 8789 and inspector port 9234. It was stopped after testing, and both ports were confirmed closed. [Official Wrangler package](https://www.npmjs.com/package/wrangler/v/4.131.1), [command reference](https://developers.cloudflare.com/workers/wrangler/commands/).

## Limits of the earlier local checks

Local timings do not establish compliance with Cloudflare Free's **10 ms cloud CPU limit**. Public hosting, real source/deployment provenance, sustained availability and cloud CPU usage remain unverified. The OpenAPI document was served and its path inventory checked; it has not been validated with an external OpenAPI validator.

No X-Agent submission, acceptance, award or payment is established by these tests. Account setup, public deployment and the event's eligibility and rights requirements remain separate steps. No account, repository, source commit, PR or public deployment was created during this local verification.
