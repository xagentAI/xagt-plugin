# Submission rights declaration

Project: `APIVouch`

Submission slug: `apivouch`

Submitter: `Shahadat Islam / SKLab Studio (GitHub submission account: @ShahadatTest)`

Date: `2026-09-19`

The submitter confirms that they own, or have sufficient authorization for, the source code, dependencies, service, data, branding, and other materials submitted in this pull request.

Subject to the official program terms, the submitter authorizes X-Agent to retain, reproduce, audit, test, archive, and publish the submitted program artifact for judging, fraud prevention, dispute handling, ecosystem submission, and post-award accountability. Closing the pull request, deleting a fork, or deleting an external repository does not revoke the official archive rights attached to an accepted and rewarded entry.

Third-party components and their licenses:

- First-party APIVouch source: MIT; full text is included at `source/LICENSE`.
- Python runtime dependencies are pinned in `source/backend/requirements.txt`; their upstream distributions retain their notices and include MIT, BSD-3-Clause, Apache-2.0, and the psycopg2 LGPL license with exceptions.
- Review/test dependencies are pinned separately in `source/backend/requirements-dev.txt` and are not bundled into the runtime image.
- Deployment uses the upstream `python:3.12-slim`, `caddy:2.10.2-alpine`, and `postgres:17.6-alpine` container images under their respective upstream terms.
- The public live demonstration reads public exchange-rate responses from Frankfurter, Floatrates, and ExchangeRate-API; it does not redistribute their services or claim ownership of their data.

Exceptions or restrictions: None beyond the third-party terms and operational limitations documented in `SUBMISSION.md`, `source/SECURITY.md`, and `source/docs/deployment.md`.

The reviewed source commit was originally authored under the SKLab Studio project identity and is being submitted through `@ShahadatTest` by the same authorized builder. The account change does not alter the source commit, service, ownership assertion, or review authorization.

This declaration records program authorization and is not a substitute for legal advice.
