# Submission rights declaration

Project: `Regimen`
Submission slug: `rayyer-regimen`
Submitter: `Yehor Ivashchenko (solo builder, GitHub: RaYYeR220)`
Date: `2026-09-19`

The submitter confirms that they own, or have sufficient authorization for, the source code, dependencies, service, data, branding, and other materials submitted in this pull request.

Subject to the official program terms, the submitter authorizes X-Agent to retain, reproduce, audit, test, archive, and publish the submitted program artifact for judging, fraud prevention, dispute handling, ecosystem submission, and post-award accountability. Closing the pull request, deleting a fork, or deleting an external repository does not revoke the official archive rights attached to an accepted and rewarded entry.

Third-party components and their licenses:

- `next` — MIT
- `react`, `react-dom` — MIT
- `zod` — MIT
- `@modelcontextprotocol/server` — MIT
- `typescript`, `vitest`, `tsx`, `@types/*` (development only) — MIT / Apache-2.0

All statistical methods are implemented from published formulas in this repository's own source; no third-party numerical or statistics library is vendored or bundled. The methods and their citations are documented in `source/src/lib/methodology.ts` and in the TSDoc of `source/src/lib/stats/`.

External services this project calls at runtime:

- **OlaXBT Nexus MCP gateway** (`https://nexus.olaxbt.xyz/api/mcp`) — read-only. Called only with an API key supplied by the caller in the `x-nexus-key` header, or with a deployment-configured demo key. Keys are never persisted and never logged; where a key must be identified for rate limiting or cache partitioning, only a non-reversible fingerprint is used. No user data is sent to any other third party.

Exceptions or restrictions: `none`

This project is published under the MIT License (`source/LICENSE`).

This template is an operational declaration, not a substitute for event terms reviewed by qualified counsel.
