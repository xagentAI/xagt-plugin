# DRAFT — SchemaBridge

Track: **Open Innovation**. The reviewed English source and API are published on Cloudflare with the owner-approved editorial interface. This is a draft package; the official entry has not been submitted.

## Capability

SchemaBridge converts small CSV or JSON exports into records with explicit field names and types. Developers and agents choose string, integer, number or boolean mappings. Invalid values produce row/field errors without partial output. It supports small imports and tool-to-tool handoffs; it is not an exact decimal accounting engine or a nested-document converter.

The English homepage at GET / explains the service and offers an editable CSV example with four fixed mappings. It sends the data to the real API and displays the returned table or errors. There is no language switch or general schema editor. The API guide at GET /docs explains request examples, mapping rules, precision, limits and errors. GET /status reads the live health response and displays its configured source commit; Refresh repeats the check. Raw JSON resources are labeled as downloads. GET /v1 remains a JSON service description; the API itself supports custom schemas and JSON input.

## Public interface

| Required link | Address |
|---|---|
| Source repository | https://github.com/wiaikit/fenix-schemabridge |
| API base | https://schemabridge.wiaikit.com/v1 |
| Health | https://schemabridge.wiaikit.com/health |
| Deployment proof | https://schemabridge.wiaikit.com/.well-known/xagent-verification.json |

POST /v1/transform accepts an application/json envelope with format, data and schema. CSV is supplied as text inside that envelope. GET /openapi.json describes the API. GET /, /docs and /status serve English HTML. Their CSS and JavaScript use local /assets/ routes. The application requires no API key or browser cookies and has no per-client rate limiter.

| Tested application limit | Value |
|---|---:|
| Request body | 32 KiB UTF-8 bytes |
| Records | 100 |
| Input fields / CSV columns | 20 |
| Schema mappings | 1–20 |
| Field name | 64 UTF-16 code units |
| String cell | 2,048 UTF-16 code units |
| Serialized JSON response | At most 64 KiB |
| Detailed field errors | Up to 40, with total count |

Output checking reserves 256 bytes for the success envelope, so amplified output can be rejected slightly below 64 KiB. Required, nullable and trim behavior are explicit. JSON numbers are parsed as IEEE-754 before validation and can already be rounded; use strings when the original digits must be checked. Integer mappings accept parsed safe integers or strict decimal integer strings. Invalid input/CSV returns 400, limits 413, unsupported content type/compression 415 and conversion errors 422. Unsupported methods return 405 and unknown paths 404.

## Source and reproduction

The reviewed source is 18d0eac794d0075df3f763bd2a442370e03f02fd. All 27 tracked files are included in source/, copied and compared byte-for-byte with exact Git blobs (2,217,942 bytes). source-manifest.json records paths, Git blobs, SHA-256 values and sizes. The editorial interface includes the original selected illustration and three locally served font files, with their notices and provenance; THIRD_PARTY.md inventories the additions.

All 32 Node tests passed with zero failures on the final main source. Wrangler 4.131.1 dry-run succeeded: 72.39 KiB bundle / 20.94 KiB gzip. Current local records and captured test/build output are included under verification/.

Public audit 2026-09-14T08:53:23.696Z to 2026-09-14T08:53:40.328Z: 24 HTTP requests, 52 assertions passed, zero failed. Exact requests, observed statuses, source comparisons and limits are in verification/current-public-checks.json. These are point-in-time observations of the published version.

All 10 current public browser checks passed: the editorial homepage and original illustration, CTA, successful CSV transform, JSON disclosure, edit invalidation, typed error, reset, readable guide, live status with exact source SHA, and home navigation. The 320 px mobile check was performed on the earlier local candidate; it is not relabeled as a fresh public mobile check. Public HTML/CSS/JS/PNG/WOFF2 bytes matched that checked candidate.

```text
npm ci --registry=https://registry.npmjs.org/
npm test
npm run build
npm run demo
npm start
```

Run from source/ with Node.js 22 or newer. npm run build is a dry-run, not publication. The source README contains setup and independent-deployment instructions. No credentials, installed dependencies or build output are submitted.

Cloudflare Worker fenix-schemabridge: version d181e389-117e-45f0-9516-56e9a96c0eb0, deployment 5e9f28ff-e340-457d-8154-65388ef55f50, 100% traffic, deployed 2026-09-14T08:51:20.584213Z. See verification/current-deployment.json. Operator control-plane observations and public byte comparisons are separate evidence; configured source metadata is not signed build attestation.

The organizer confirmed on 15 September 2026 at 06:23 UTC that public endpoints must identify the source commit used for the submitted and deployed service; it does not need to match the final PR head in the X-Agent submission repository. The published sourceRepository/reviewCommit values therefore remain bound to the source SHA above. Submit the corresponding source/ snapshot and source-manifest.json, and compare the submitted source files with that manifest. The organizer reviews and merges entries individually. The official PR has not been created; its eventual head is a separate submission identifier, not a replacement for the service source SHA. This version-mapping clarification is resolved.

These checks do not establish continuous review-period availability, load capacity, provider retention or a hosting CPU guarantee. No future award or payment is assumed. Use synthetic or non-sensitive data. The visual release changes presentation and static-asset delivery; its scope and any untested scenarios are recorded in the current local/public/browser evidence.

## Data handling

The status page makes an initial same-origin GET /health and repeats it on Refresh, without cookies or followed redirects; it makes no healthy claim before a valid response. Its status is an observation, not an uptime or build-provenance guarantee. The homepage script submits only on user action to the same-origin transform endpoint, omits credentials, rejects redirects and uses no browser storage. Returned values/errors are rendered as text. The application processes records in request memory without persistence, external API calls or cell-value logging. Errors can include schema names and row indexes. The fixtures are synthetic; use synthetic or non-sensitive data for review.

Runtime code has no external packages, model calls, database, payment integration, user-defined code or URL imports. CSP permits the page's same-origin assets and API calls without inline/eval permission. Provider transport logging/retention has not been independently audited. Request bounds do not establish hosting capacity, uptime, abuse protection or Cloudflare Free CPU compliance.

## Contact and status

Working name: Fenix. Support: wiaikit@proton.me.

Aleksandr Parkhomenko approved the completed RIGHTS.md declaration on 2026-09-15, including the disclosed third-party conditions. This approval is explicit and is not inferred from public source access; no additional unrestricted open-source license is granted. Registration, official community membership and official PR submission remain pending; see HUMAN_REQUIREMENTS.md.
