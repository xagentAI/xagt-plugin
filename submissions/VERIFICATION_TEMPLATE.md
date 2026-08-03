# Verification evidence

Copy this file to `submissions/mcp-hackathon/<your-project>/verification/README.md` and replace the placeholders.

## Prerequisites

- Review commit: `<40-character commit SHA>`
- API base URL: `<https://api.example.com/v1>`
- Authentication: `<how a reviewer obtains short-lived access without committing a secret>`

## 1. Health check

```bash
curl --fail --silent --show-error https://api.example.com/health
```

Expected response:

```json
{"status":"ok","commit":"<40-character review commit>"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://api.example.com/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"<team-or-builder>-<project-slug>","commit":"<40-character review commit>"}
```

## 3. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://api.example.com/v1/<capability> \
  --header "content-type: application/json" \
  --data '{"<input>":"<value>"}'
```

State the expected success response and one safe failure response. Redact all tokens, user data, and production identifiers.
