# BountyLens

## Capability

- **One-line description:** Evaluate whether a public GitHub Issue is worth pursuing before a developer or coding agent spends implementation time or compute.
- **Who it helps:** Coding agents, independent developers, small engineering teams, and automated workflows triaging public GitHub contribution opportunities.
- **Capability boundary:** BountyLens reads public GitHub Issue, comment, repository, activity, and language metadata; extracts explainable opportunity signals; and returns a deterministic score, decision, confidence, and effort range. It does not guarantee payment or acceptance, access private repositories, execute target code, claim Issues, open pull requests, or perform security, scam, wallet, or compliance analysis.

## Live API

- **API base URL:** https://bountylens-api.onrender.com
- **Health-check URL:** https://bountylens-api.onrender.com/health
- **Authentication:** None for reviewers. A GitHub token is used only by the deployed server to raise its upstream read quota and is never exposed to clients.
- **Rate limits / known limits:** Each GitHub request has a 10-second timeout; request bodies are limited to 16 KiB; Issue comments are limited to the first 100; successful Issue context is cached in memory for 300 seconds. GitHub upstream limits can produce HTTP 429, and a free Render instance can have a cold-start delay after inactivity.
- **API contract:** [`source/openapi.yaml`](./source/openapi.yaml)

## Source and reproducibility

- **Source repository:** https://github.com/bowenhb/bountylens
- **Review commit:** `752c513d63b141b7acbf812ac71f33d5d99a98e1`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm ci && npm run typecheck && npm test && npm run build`
- **Run locally:** `npm ci && cp .env.example .env && npm run dev`
- **Deploy:** Build with `docker build -t bountylens:review .`, then run with `docker run --rm -p 3000:3000 -e SOURCE_COMMIT=752c513d63b141b7acbf812ac71f33d5d99a98e1 -e PROJECT_SLUG=bowenhb-bountylens bountylens:review`. On Render, deploy the included Dockerfile from the review commit and set `NODE_ENV=production`, the same `SOURCE_COMMIT`, and `PROJECT_SLUG=bowenhb-bountylens`; an optional server-side `GITHUB_TOKEN` raises the public GitHub API quota.
- **Version binding:** `/health` reports the exact review commit. The same-origin `/.well-known/xagent-verification.json` reports schema version 1, submission slug `bowenhb-bountylens`, and the same commit. Render automatic deployment is disabled so the reviewed version remains pinned.

The deployed service returns:

```json
// GET https://bountylens-api.onrender.com/health
{"status":"ok","commit":"752c513d63b141b7acbf812ac71f33d5d99a98e1"}
```

```json
// GET https://bountylens-api.onrender.com/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"bowenhb-bountylens","commit":"752c513d63b141b7acbf812ac71f33d5d99a98e1"}
```

## Verification

Reproducible calls and redacted expected responses are in [`verification/README.md`](./verification/README.md).

- **Health-check result:** HTTP 200 with `status=ok` and the exact 40-character review commit.
- **Capability call:** `POST /v1/evaluate` with a public GitHub Issue URL and an optional developer profile. The documented example evaluates `fastify/fastify#7030`.
- **Expected error behavior:** Invalid or non-GitHub Issue URLs return HTTP 400 and `INVALID_ISSUE_URL`; missing Issues return 404; GitHub rate limits return 429; upstream timeouts return 504; oversized request bodies return 413. Errors use a stable JSON envelope and do not expose upstream bodies or credentials.

## Security and data handling

- **Data collected:** The request contains a public GitHub Issue URL and may include developer languages, hourly rate, and maximum hours. The service reads public Issue, comment, repository, and language metadata from GitHub.
- **Purpose and retention:** Inputs are used only to produce the requested assessment. There is no database or persistent user storage. Normalized public GitHub context can remain in the process-local cache for up to 300 seconds. Structured logs record request ID, route, status, duration, and safe upstream status metadata, but omit request bodies, developer profiles, credentials, and private upstream errors.
- **Third parties / outbound network calls:** Read-only calls to the public GitHub REST API. The public deployment is hosted by Render.
- **Secrets:** No secrets are committed. The optional GitHub token is stored only in the deployment environment and is used only in the outbound GitHub `Authorization` header.
- **Known risks / restrictions:** Results reflect public metadata available at request time and scores can change as an Issue or repository changes. Reward evidence is limited to explicit USD signals; BountyLens does not predict payment, acceptance, legal eligibility, or project safety. The service does not execute repository code.

## Support

- **Team / builder:** hebo (`@bowenhb` on GitHub)
- **Contact:** https://github.com/bowenhb/bountylens/issues
- **License / rights:** The submitted first-party source is MIT licensed. The submitter authored or is authorized to submit the project and grants the review and archival rights stated in `RIGHTS.md`.
