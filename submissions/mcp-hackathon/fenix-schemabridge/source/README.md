# SchemaBridge

SchemaBridge turns small CSV or JSON record sets into a declared set of fields. You choose each source field, output name and type. If a field cannot be converted, the response explains where it failed and returns no partial records.

This project implements the SchemaBridge idea for X-Agent Open Innovation. Deployment and contest acceptance are separate from the implementation and its local verification. It uses no runtime packages, external APIs, model calls, database, payment service or uploaded-file storage.

## Run locally

Node.js 22 or newer and npm are required for the development toolchain. From this directory, install the exact dependencies in the committed lockfile, run the tests, and create a local dry-run bundle:

```text
npm ci --registry=https://registry.npmjs.org/
npm test
npm run build
```

Wrangler 4.131.1 is an exact development dependency; `package-lock.json` records its transitive dependencies and integrity hashes. `npm ci` installs that locked toolchain from the official npm registry. The build uses the installed local Wrangler, writes `dist/cloudflare/`, and exits without publishing or requiring a Cloudflare login. Keep `package.json` and `package-lock.json` together when copying the source.

The earlier lockfile release was checked locally with Node.js 24.16.0 and npm 11.13.0: `npm ci` succeeded, all 32 existing tests passed, and its dry-run build reported 64.28 KiB / 18.39 KiB gzip. All 91 resolved package entries use `https://registry.npmjs.org/` and carry integrity hashes. Those measurements describe the earlier release, not the later visual assets; repeat the commands above to check the current source.

The application itself has no runtime dependencies. Its tests, demo and loopback server can also run with Node alone, without installing the development toolchain:

```text
node --test
node tools/demo.mjs
node tools/serve.mjs
```

The demo calls the Worker handler in memory with the three fixture requests. The server command starts a small development HTTP adapter at `http://127.0.0.1:8787`. Stop it with Ctrl+C. The adapter binds only to loopback; it is not a public hosting setup. Set `PORT` if the default port is occupied. Equivalent npm scripts are provided as `test`, `demo` and `start`.

For example, in another PowerShell terminal in this directory:

```powershell
$sampleBody = Get-Content -LiteralPath 'fixtures/csv-request.json' -Raw
Invoke-RestMethod -Uri 'http://127.0.0.1:8787/v1/transform' -Method Post -ContentType 'application/json' -Body $sampleBody
```

The example returns two records. Tea has quantity `7` and availability `true`; coffee has quantity `0` and availability `false`. `fixtures/csv-expected.json` gives the complete expected response. `json-request.json` demonstrates explicit trimming, a nullable field and an omitted optional field. `invalid-request.json` produces HTTP 422 with two field errors.

## HTTP interface

| Method and path | Purpose |
|---|---|
| `GET /` | Open the English homepage and run an editable CSV example. |
| `GET /docs` | Read the English API guide, examples, field rules and error reference. |
| `GET /status` | Open the status page, which checks the real `/health` response. |
| `GET /v1` | Read the JSON API description, capability method/path and documentation links. |
| `POST /v1/transform` | Convert in-body records using the supplied schema. |
| `GET /health` | Report a configured reviewed source commit, or HTTP 503 when missing/invalid. |
| `GET /.well-known/xagent-verification.json` | Report the configured project slug and source commit, or HTTP 503. |
| `GET /openapi.json` | Read the minimal OpenAPI 3.1 description. |

The transformation endpoint always takes an `application/json` envelope, including for CSV:

```json
{
  "format": "json",
  "data": [{ "stock": "7", "active": "false" }],
  "schema": [
    { "source": "stock", "target": "quantity", "type": "integer" },
    { "source": "active", "target": "available", "type": "boolean" }
  ]
}
```

For CSV, set `format` to `"csv"` and provide the text as `data`. The first row is the header. The parser supports comma separators, LF/CRLF record endings, quoted cells, escaped double quotes and newlines inside quoted cells. A leading CSV BOM is accepted. Headers must be unique and non-empty. Blank records are not skipped. A final line ending does not create another record. Wrong column counts or broken quotes return an error; they are not repaired silently. Header-only CSV and an empty JSON array produce an empty result.

JSON input must be an array of flat objects. All cells, including unmapped cells, must be strings, finite numbers, booleans or null. Field names are literal top-level keys; dots do not address nested objects. Unmapped fields are left out of the output. The reserved names `__proto__`, `prototype` and `constructor` are rejected. Schema targets must be unique, though a source may be mapped to several targets.

### Field conversion

| Target type | Accepted values |
|---|---|
| `string` | String, finite number or boolean. Numbers and booleans are converted to text. |
| `integer` | A parsed IEEE-754 number that is a safe integer, or a strict decimal integer string. Strings cannot contain fractions, exponents, leading plus or extra leading zeros. Values outside JavaScript's safe integer range are rejected. |
| `number` | A finite number, or a JSON-style decimal string, including an exponent. Hexadecimal and non-finite values are rejected. |
| `boolean` | A boolean, or exactly `"true"` or `"false"`. `1`, `"yes"` and `"TRUE"` are not accepted. |

Numbers use JavaScript's IEEE-754 representation. JSON parsing happens before field validation: a raw JSON number such as `1.0000000000000001` rounds to `1`, and numeric `1e2` becomes `100`. The integer check sees those parsed values, not their original spelling. Send numeric data as strings when the original digits must be validated; for example, the string `"1.0000000000000001"` is rejected by an integer mapping. This is not a decimal accounting engine. Send identifiers or integers beyond the safe integer range as strings and keep the target type `string` if their exact digits matter.

Each mapping accepts three optional switches: `required` defaults to `true`, `nullable` to `false`, and `trim` to `false`. A missing optional field is omitted. `nullable: true` preserves an explicit null. Empty CSV cells are empty strings, not null. `trim: true` trims string input before conversion; it never runs automatically. Unknown envelope or schema options are rejected. There are no arbitrary expressions, user-defined code, URL imports or regex transformations.

The success summary counts input/output rows, mappings and cells whose value or type changed after JSON parsing. It does not count rounding performed by the JSON parser. Renaming a field alone is not a cell conversion. Missing optional fields and retained nulls do not increase that count.

### Limits and errors

| Limit | Value |
|---|---:|
| Request body, UTF-8 bytes | 32 KiB, enforced while reading |
| Records | 100 |
| Input fields per record / CSV columns | 20 |
| Schema mappings | 1–20 |
| Source or target name | 64 UTF-16 code units |
| String cell | 2,048 UTF-16 code units |
| Serialized response | 64 KiB maximum |
| Detailed field errors | 40, with a total error count |

The transform also reserves 256 bytes for its success envelope when checking accumulated output. It can therefore reject amplified output slightly below 64 KiB. The Worker handler does not log request bodies or cell values; the offline demo prints only its synthetic fixture results. Errors can include schema names and zero-based row indexes, but do not echo cell values or return a stack trace. Example:

```json
{
  "ok": false,
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Some fields could not be converted. No records were returned.",
    "details": {
      "totalErrors": 1,
      "truncated": false,
      "fields": [{ "row": 0, "source": "stock", "target": "quantity", "expected": "integer", "code": "TYPE_MISMATCH" }]
    }
  }
}
```

Invalid structure or CSV uses HTTP 400; size limits use 413; unsupported content type or compression uses 415; failed field conversions use 422. Unsupported methods return 405 with `Allow`; unknown routes return 404. Unexpected handler errors return a generic 500. Responses are JSON and carry `Cache-Control: no-store`. The Worker has no mutable request state and does not persist records. The local HTTP adapter has its own bounded transport buffer; it is only a development aid.

## Commit evidence and deployment boundary

The [official X-Agent README](https://github.com/xagentAI/xagt-plugin) was checked on 12 September 2026. It requires a public health response with `status` and the reviewed commit, plus a same-origin `/.well-known/xagent-verification.json` response containing `schemaVersion: 1`, `slug` and that commit. These routes implement those shapes.

The deployment operator must supply `REVIEW_COMMIT` as the actual full 40-character hexadecimal source SHA. The proof route additionally requires `PROJECT_SLUG`, such as `fenix-schemabridge`. Missing, malformed or all-zero commits return HTTP 503, with no invented SHA or successful proof. Neither variable is set in `wrangler.jsonc`. Read the real source SHA from Git when preparing a deployment; test values in the test file are explicitly synthetic.

The handler cannot verify GitHub or deployment provenance without an external request, and deliberately does not make one. A syntactically valid supplied SHA is reported as supplied. Before any submission, the operator must independently match that SHA to the public source and deployed version, then test the real public endpoints. Local health should currently return 503; that is expected.

### Before deployment and entry

Use this sequence when preparing a release. A local source commit does not establish a public deployment or contest entry.

1. **Review the source.** Confirm the intended project files, fixtures and tests. Exclude local environment files, `.wrangler`, dependency caches and credentials. Resolve any review findings before recording the deployment version.
2. **Record a real commit.** Commit that reviewed source in its intended repository. Confirm the checkout is clean with `git status --porcelain`, then read the full SHA using `git rev-parse --verify 'HEAD^{commit}'`. Make the same commit publicly reviewable before entering the event. Do not use a test SHA or commit only an unrelated wrapper.
3. **Configure and deploy that checkout.** Set `REVIEW_COMMIT` to the recorded SHA and `PROJECT_SLUG` to the agreed entry slug in the deployment variables. Keep the SHA outside the source it identifies. Deploy exactly that checkout and retain the resulting deployment/version reference. If the source changes, use its new commit and repeat verification.
4. **Verify the public service.** Without dashboard authentication, check that `/health` returns HTTP 200 with `status: "ok"` and the recorded commit. The same origin's `/.well-known/xagent-verification.json` must return HTTP 200 with `schemaVersion: 1`, the agreed slug and exactly the same commit. Check the CSV fixture against `csv-expected.json`, the JSON fixture and the expected 422 error fixture. Record the URLs and results alongside the source and deployment version. The local smoke script is restricted to loopback and is not a public-deployment verifier.
5. **Prepare the entry from verified evidence.** Follow the official submission templates for `SUBMISSION.md`, `submission.json`, `RIGHTS.md`, complete `source/`, and `verification/README.md` under one `submissions/mcp-hackathon/<project-slug>/` directory. Use the real URLs, source SHA and documented calls; complete registration and the applicable rights declaration before submission. Keep the service reachable for the announced review window and any agreed acceptance checks. Successful HTTP checks alone do not establish eligibility, an award or payment.

The required health/proof shapes and source package above follow the [official submission instructions](https://github.com/xagentAI/xagt-plugin). This checklist does not authenticate, publish or create a commit, and no deployment script is needed to generate a SHA: Git must supply it from the reviewed source.

## Test in the local Workers runtime

`wrangler.jsonc` is a configuration starting point for Cloudflare Workers. The runtime entry uses standard Worker Request/Response APIs; the Node-only files under `tools/` and `test/` are not imported by it. On 12 September, the official Wrangler **4.131.1** ran this entry in local workerd and passed **29 HTTP smoke checks**. No runtime compatibility fix was needed. Cloudflare Free's **10 ms CPU limit**, continuous availability, contest eligibility and any payout require separate verification; successful local checks do not establish them. Local request timings do not measure Workers CPU time. [Cloudflare limits](https://developers.cloudflare.com/workers/platform/limits/).

To repeat the local workerd check, first run `npm ci` as shown above, then start the installed local CLI in one terminal and the smoke script in another. These commands use the local runtime with remote bindings disabled; no login or public deployment is needed. Confirm the two selected ports are free before starting.

```powershell
$env:WRANGLER_SEND_METRICS = 'false'
npm.cmd run wrangler -- dev --local --ip 127.0.0.1 --port 8789 --inspector-ip 127.0.0.1 --inspector-port 9234 --show-interactive-dev-session=false
```

```text
node tools/workerd-smoke.mjs http://127.0.0.1:8789
```

The smoke script only permits an HTTP origin on `127.0.0.1` and expects unconfigured health/proof routes. Stop Wrangler with Ctrl+C after testing. Generated `.wrangler` files, local environment files and dependency directories are excluded by `.gitignore`; they are not submission source.

## Cloudflare deployment

The production address is [schemabridge.wiaikit.com](https://schemabridge.wiaikit.com/). The homepage explains the service and offers a live CSV example in English. The example uses four fixed mappings; edit its CSV and run it to see the actual API response as a table. A general schema editor is not included. The developer links open the readable [API guide](https://schemabridge.wiaikit.com/docs) and [live status page](https://schemabridge.wiaikit.com/status). Machine endpoints continue to return JSON: [API index](https://schemabridge.wiaikit.com/v1), [health](https://schemabridge.wiaikit.com/health), [deployment proof](https://schemabridge.wiaikit.com/.well-known/xagent-verification.json), and [OpenAPI document](https://schemabridge.wiaikit.com/openapi.json). All use the same Cloudflare custom domain.

After `npm ci`, `npm run build` uses the locally installed Wrangler 4.131.1 and its locked dependencies to bundle the Worker modules into `dist/cloudflare/` with `--dry-run`. It does not publish or require account credentials. Generated output and local credentials are excluded from Git.

The production configuration binds only `schemabridge.wiaikit.com`; the existing root website and other account projects are separate. It deploys the illustration and locally hosted fonts from `public/` through the `ASSETS` binding. The Worker runs before static assets and only permits the four named PNG/WOFF2 resources; repository files and other paths are not exposed. Keep `public/`, including its font notices, with the source when building or deploying. See [ASSETS.md](ASSETS.md) for provenance and licenses. For an independent deployment, choose your own Worker name and replace the custom domain in `wrangler.jsonc` with a domain you control, or remove `routes` to use your own `workers.dev` address. Review and commit your resulting source before publishing.

Install the locked toolchain with `npm ci`, then authenticate the installed official Wrangler CLI in your own account. With the reviewed checkout clean, deploy from PowerShell as follows. `CLOUDFLARE_ACCOUNT_ID` must identify the intended account; credentials belong in Wrangler's supported credential store or a private environment variable, never in source.

```powershell
$reviewCommit = (git rev-parse --verify 'HEAD^{commit}').Trim()
if (git status --porcelain) { throw 'Commit reviewed changes before deploying.' }
$env:WRANGLER_SEND_METRICS = 'false'
npm.cmd run wrangler -- deploy --var "REVIEW_COMMIT:$reviewCommit" --var 'PROJECT_SLUG:fenix-schemabridge'
```

Supply both variables on every release: dashboard-only values can be overwritten by Wrangler. The SHA is kept outside the source it identifies. After deployment, reconcile the Cloudflare version with the reviewed checkout and independently check health, proof and fixture responses. A configured SHA alone does not prove that matching code was uploaded. See [Cloudflare Custom Domains](https://developers.cloudflare.com/workers/configuration/routing/custom-domains/) and [Wrangler configuration](https://developers.cloudflare.com/workers/wrangler/configuration/).

## File guide

The public API has no application authentication or per-client rate limiter. It accepts only bounded, in-memory transformations: no outbound fetches, code execution or persistence. Request limits do not establish service capacity or continuous availability. The application does not log request bodies; provider transport logs and their retention are governed by the hosting provider and have not been independently audited. Use synthetic or non-sensitive data for evaluation.

- `src/homepage.mjs`: accessible homepage, local stylesheet and browser script; all demo requests use the same API origin.
- `src/docs.mjs`: English API guide and status page; status is read from the real same-origin health endpoint.
- `src/transform.mjs`: schema checks, CSV parser and conversion logic.
- `src/worker.mjs`: bounded HTTP body reading, route handling and commit responses.
- `src/openapi.mjs`: the API description served by the Worker.
- `public/assets/`: the original bridge illustration and three self-hosted webfonts, with font licenses and source metadata. Browser styling uses no external font server.
- `ASSETS.md`: current visual-asset provenance and third-party font notices.
- `fixtures/`: synthetic requests and expected CSV result.
- `tools/`: offline demo and loopback development adapter.
- `tools/workerd-smoke.mjs`: real HTTP checks against a separately started local Wrangler server.
- `test/worker.test.mjs`: behavior and boundary checks, including real loopback HTTP.
- `VERIFICATION.md`: what was actually run and what remains unverified.

Publication does not grant an unrestricted license or accept the event rights declaration. Contest registration, the applicable declaration and submission remain separate steps.
