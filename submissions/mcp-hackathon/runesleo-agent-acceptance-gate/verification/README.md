# Verification evidence

Live evidence captured after owner-authorized public deploy of commit `15c007b4a785a1263df989bb72c6e10e4b60ddf4`.

## Prerequisites

- Review commit: `15c007b4a785a1263df989bb72c6e10e4b60ddf4`
- Public source: https://github.com/runesleo/agent-acceptance-gate/commit/15c007b4a785a1263df989bb72c6e10e4b60ddf4
- API base URL: `https://api.leolabs.me`
- Authentication: none during the approved reviewer window

## 1. Health check

```bash
curl --fail --silent --show-error https://api.leolabs.me/health
```

Frozen live response: `verification/live-health.json`

Required fields include:

```json
{"status":"ok","commit":"15c007b4a785a1263df989bb72c6e10e4b60ddf4"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://api.leolabs.me/.well-known/xagent-verification.json
```

Frozen live response: `verification/live-proof.json`

Expected response:

```json
{"schemaVersion":1,"slug":"runesleo-agent-acceptance-gate","commit":"15c007b4a785a1263df989bb72c6e10e4b60ddf4"}
```

## 3. Capability call

From this submission directory:

```bash
curl --fail --silent --show-error \
  --request POST https://api.leolabs.me/xagent/agent-delivery-acceptance-audit \
  --header "content-type: application/json" \
  --data @verification/request.json
```

Frozen live response: `verification/example-success.json`. A `needs_review` verdict is expected for this fixture because its public-release gate text remains intentionally conservative in the sample input; the capability must not falsely mark that state as accepted.

Safe invalid-input call:

```bash
curl --silent --show-error \
  --request POST https://api.leolabs.me/xagent/agent-delivery-acceptance-audit \
  --header "content-type: application/json" \
  --data '{"task":"Missing delivery summary"}'
```

Expected status: HTTP 400. Frozen response: `verification/example-safe-error.json`.

## 4. Offline project checks

```bash
cd source
npm ci
npm test
npm run worker:check
```
