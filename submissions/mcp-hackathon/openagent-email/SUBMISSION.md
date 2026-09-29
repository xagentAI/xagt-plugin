# openagent.email — Email API for AI Agents

## Capability

- **One-line description:** Gives any AI agent a real email address it fully controls — receive mail, extract OTP codes and confirmation links, send mail, and get webhook/push notifications — through a REST API and an MCP server.
- **Who it helps:** AI agents and the people building them. Any agent that needs to sign up for a service, verify an account, receive a magic link, or read and answer email autonomously can use this as its email infrastructure.
- **Capability boundary:** The service creates and manages email identities (addresses), receives inbound mail into a catch-all mailbox and parses it per identity (including OTP code and verification-link extraction), sends outbound mail with per-identity sender addresses, and exposes everything through REST `/v1/*` endpoints and 20 MCP tools (`@openagentemail/mcp` on npm). It is a self-hosted email platform (docker-mailserver + our API); the submitted live API is our hosted demo instance. It does not provide on-chain, security-audit, or content-screening functionality.

## Live API

- **API base URL:** https://demo.openagent.email/v1
- **Health-check URL:** https://demo.openagent.email/healthz
- **Authentication:** Bearer token (API key). A short-lived reviewer token is supplied through the program's private review channel on request. MCP clients use OAuth (RFC 9728/8414 discovery endpoints are live on the same origin).
- **Rate limits / known limits:** No request-rate limit on the demo instance beyond a 1 MiB JSON body cap; typical responses well under 5s. Outbound delivery to external providers is restricted on the demo instance; inbound receive, identity management, MCP tools, and intra-instance send are fully functional.
- **API contract:** `source/docs/api.md` documents every `/v1` endpoint; MCP tools are described in `source/docs/mcp-clients.md` and `source/packages/mcp/README.md`.

## Source and reproducibility

- **Source repository:** https://github.com/openagentemail/openagentemail
- **Review commit:** `5f432e4bd4019bda1f04ae5d6863975cff7721eb`
- **Source submitted in this PR:** `source/`
- **Run tests:** `cd packages/api && bun test` (also `cd packages/mcp && bun test`, `cd packages/setup && bun test`)
- **Run locally:** `cp .env.example .env` (fill in `DOMAIN`, `API_KEYS`, `MAIL_PASSWORD`) then `docker compose up -d`; helper scripts `deploy/dns-records.sh` and `deploy/doctor.sh`
- **Deploy:** Same compose flow on any Docker host; see `source/docs/operator-guide.md`. The demo instance runs exactly this compose stack (API image built from the review commit).
- **Version binding:** The API image is built with `SOURCE_COMMIT` set to the exact review commit; the running service reports it in `/healthz` (`commit` field) and in `/.well-known/xagent-verification.json`.

The API must expose:

```json
// GET https://demo.openagent.email/healthz
{"ok":true,"status":"ok","commit":"5f432e4bd4019bda1f04ae5d6863975cff7721eb","version":"<api version>"}
```

```json
// GET https://demo.openagent.email/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"openagent-email","commit":"5f432e4bd4019bda1f04ae5d6863975cff7721eb"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** HTTP 200 with `status: "ok"` and the review commit.
- **Capability call:** `POST /v1/identities` creates a working mailbox (returns an address like `reviewer-bot@demo.openagent.email` and its token); `GET /v1/messages?address=...` then lists what it received, including parsed OTP codes.
- **Expected error behavior:** Calling `/v1/*` without a bearer token returns HTTP 401 with a JSON error body; invalid payloads return 400-class JSON errors; no stack traces or internal data leak.

## Security and data handling

- **Data collected:** Email messages addressed to identities created on the instance, plus identity/task metadata. No analytics or tracking.
- **Purpose and retention:** Mail is stored to serve the API, for the lifetime of the instance; reviewer-created identities and their mail can be deleted on request or with the instance after the program.
- **Third parties / outbound network calls:** Inbound SMTP via docker-mailserver (Postfix/Dovecot/OpenDKIM, runtime image, not bundled); optional self-hosted ntfy push notifications (off by default); outbound SMTP restricted on the demo instance. No other outbound calls.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** The demo instance is a shared review environment; do not send personal or production data to it. The API enforces bearer auth and per-token scope policies (`packages/api/src/lib/scope-policy.ts`).
- **Source completeness note:** `source/` is a byte-exact snapshot of the review commit except three security-test files excluded because their intentional fake-credential canaries trip the baseline secret scan: `packages/api/test/audit-tiering.test.ts`, `examples/adapters/test/persisted-string-matrix.test.ts` and `examples/adapters/test/r1d-evidence-matrix.test.ts` (they contain a PEM private-key-header stub and `sk-…` canary strings used to prove our own credential redaction; every value is fake and clearly labeled). All three are readable in the public repository at the same commit; nothing else is excluded.

## Support

- **Team / builder:** openagent.email (Tizer Luo)
- **Contact:** support@openagent.email
- **License / rights:** Apache-2.0 (see `source/LICENSE`). The submitter owns the submitted code and can authorize review and deployment; third-party components and licenses are listed in `RIGHTS.md`.
