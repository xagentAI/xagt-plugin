# Verification evidence

## Prerequisites

- Review commit: `ce5429415671e1af0f3d8cc9418f2ea7d69bd9f6`
- API base URL: `https://release-radar-api.diogosouzac.workers.dev/v1`
- Authentication: none

## 1. Health check

```sh
curl --fail --silent --show-error https://release-radar-api.diogosouzac.workers.dev/health
```

Expected response:

```json
{"status":"ok","version":"0.1.0","commit":"ce5429415671e1af0f3d8cc9418f2ea7d69bd9f6"}
```

## 2. Deployment proof

```sh
curl --fail --silent --show-error https://release-radar-api.diogosouzac.workers.dev/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"aridclown-release-radar","commit":"ce5429415671e1af0f3d8cc9418f2ea7d69bd9f6"}
```

## 3. Capability call

```sh
curl --fail --silent --show-error \
  'https://release-radar-api.diogosouzac.workers.dev/v1/releases?repo=vercel%2Fnext.js&limit=1'
```

Expected response shape:

```json
{
  "repo": "vercel/next.js",
  "count": 1,
  "releases": [{"tag":"v16.4.0-canary.34","highlights":["Misc Changes"],"breakingSignals":[]}]
}
```

For safe error behavior:

```sh
curl --silent 'https://release-radar-api.diogosouzac.workers.dev/v1/releases?repo=not-a-repo'
```

Expected response:

```json
{"error":"invalid_repo","message":"Use repo=owner/repository."}
```
