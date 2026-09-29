# Release Radar API

## Capability

- **One-line description:** Converts public GitHub release notes into compact upgrade signals that an agent can use before changing a dependency.
- **Who it helps:** Developers and coding agents planning a dependency upgrade.
- **Capability boundary:** Reads only public GitHub release and comparison metadata. It does not access private repositories, authenticate as a GitHub user, modify repositories, or make upgrade decisions.

## Live API

- **API base URL:** `https://release-radar-api.diogosouzac.workers.dev/v1`
- **Health-check URL:** `https://release-radar-api.diogosouzac.workers.dev/health`
- **Authentication:** None.
- **Rate limits / known limits:** The service requests GitHub's unauthenticated public Releases API. GitHub's public rate limits apply; responses are cached for five minutes. `limit` accepts integers from 1 through 10.
- **API contract:** `GET /v1/releases?repo=owner/repository&limit=5` returns non-draft releases with `highlights` and heuristic `breakingSignals` extracted from release-note lines. `GET /v1/compare?repo=owner/repository&base=ref&head=ref` returns changed-file areas and commit subjects for an upgrade plan. `GET /openapi.json` provides the machine-readable contract.

## Source and reproducibility

- **Source repository:** `https://github.com/aridclown/release-radar-api`
- **Review commit:** `4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810`
- **Source submitted in this PR:** `source/`
- **Run tests:** `npm test`
- **Run locally:** `npm install && npm run dev`
- **Deploy:** `npx wrangler deploy --var COMMIT:4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810 --var SLUG:aridclown-release-radar`
- **Version binding:** Cloudflare Worker deployment variables bind the committed source SHA and submission slug into `/health` and `/.well-known/xagent-verification.json`.

The health endpoint returns:

```json
{"status":"ok","version":"0.1.0","commit":"4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810"}
```

The same-origin proof endpoint returns:

```json
{"schemaVersion":1,"slug":"aridclown-release-radar","commit":"4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810"}
```

## Verification

Repeatable commands and expected results are in `verification/README.md`.

- **Health-check result:** HTTP 200 with `status: ok` and the review commit.
- **Capability call:** `GET /v1/compare?repo=vercel/next.js&base=v16.4.0-canary.33&head=v16.4.0-canary.34` returned HTTP 200 with 11 commits, 140 changed files, and per-area counts on September 17, 2026.
- **Expected error behavior:** invalid repository input returns HTTP 400 and a documented `invalid_repo` response; a missing public repository returns HTTP 404.

## Security and data handling

- **Data collected:** None. The API receives a public GitHub repository name in the request URL; it does not persist request data.
- **Purpose and retention:** Release metadata is fetched from GitHub and cached at the edge for five minutes to reduce upstream requests.
- **Third parties / outbound network calls:** Public GitHub REST Releases API only.
- **Secrets:** No secrets are committed. The deployed service needs no secret or reviewer credential.
- **Known risks / restrictions:** Release-note classification is intentionally heuristic. Consumers must follow the linked upstream release notes before making material upgrade decisions.

## Support

- **Team / builder:** Julio Sampaio (`aridclown` on GitHub)
- **Contact:** GitHub issue in the source repository.
- **License / rights:** The submitter authorizes review and deployment of this original project. Third-party package licenses are declared in `RIGHTS.md`.
