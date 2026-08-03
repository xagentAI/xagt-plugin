# <Project name>

> Replace every angle-bracket placeholder before opening the pull request.

## Capability

- **One-line description:** <the real task an agent can complete>
- **Who it helps:** <user or system>
- **Capability boundary:** <what it does and does not do>

## Live API

- **API base URL:** <https://api.example.com/v1>
- **Health-check URL:** <https://api.example.com/health>
- **Authentication:** <none | API key via private review channel | OAuth | other>
- **Rate limits / known limits:** <limits and expected timeout>
- **API contract:** <link to OpenAPI file in source/ or describe request/response here>

## Source and reproducibility

- **Source repository:** <https://github.com/owner/repo>
- **Review commit:** `<40-character commit SHA>`
- **Source submitted in this PR:** `source/`
- **Run tests:** `<exact command>`
- **Run locally:** `<exact command>`
- **Deploy:** `<exact command or documented steps>`
- **Version binding:** <how the deployed service exposes or records this commit>

The API must expose:

```json
// GET <health-check URL>
{"status":"ok","commit":"<40-character commit SHA>"}
```

```json
// GET /.well-known/xagent-verification.json on the same API origin
{"schemaVersion":1,"slug":"<team-or-builder>-<project-slug>","commit":"<40-character commit SHA>"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** <status and expected response>
- **Capability call:** <endpoint and one example input>
- **Expected error behavior:** <invalid input, authorization, timeout, or limit behavior>

## Security and data handling

- **Data collected:** <fields or none>
- **Purpose and retention:** <why and for how long>
- **Third parties / outbound network calls:** <services or none>
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** <anything reviewers or downstream agents must know>

## Support

- **Team / builder:** <name>
- **Contact:** <preferred contact channel>
- **License / rights:** <license and confirmation that the submitter can authorize review and deployment>
