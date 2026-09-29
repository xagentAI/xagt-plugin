# Submission rights declaration

Project: `Abstain`
Submission slug: `faroukobayanju-abstain`
Submitter: `faroukobayanju`
Date: `2026-09-18`

The submitter confirms that they own, or have sufficient authorization for, the source code, dependencies, service, data, branding, and other materials submitted in this pull request.

Subject to the official program terms, the submitter authorizes X-Agent to retain, reproduce, audit, test, archive, and publish the submitted program artifact for judging, fraud prevention, dispute handling, ecosystem submission, and post-award accountability. Closing the pull request, deleting a fork, or deleting an external repository does not revoke the official archive rights attached to an accepted and rewarded entry.

Third-party components and their licenses:

| Component | Version | License | Role |
| --- | --- | --- | --- |
| `hono` | 4.13.8 | MIT | HTTP routing |
| `@hono/node-server` | 1.x | MIT | local server for the demo and verification steps |
| `typescript` | 5.6.x | Apache-2.0 | build only |
| `vitest` | 2.1.x | MIT | test only |
| `@types/node` | latest | MIT | types only |

No Upstash or Redis SDK is used: the three Redis commands required (`GET`, `LRANGE`, `EVAL`) are issued over the Upstash REST API with the platform `fetch`, in `source/src/store/upstash.ts`.

Market and strategy data under `source/fixtures/` was retrieved from the OlaXBT Nexus MCP gateway using an API key bound to the submitter's own strategy `str_515920d047ca`. Files are recorded responses about the submitter's own strategy and public market series. Provenance for every file, including three clearly labelled synthetic fixtures, is declared in `source/fixtures/README.md`.

Exceptions or restrictions: `none`

This template is an operational declaration, not a substitute for event terms reviewed by qualified counsel.
