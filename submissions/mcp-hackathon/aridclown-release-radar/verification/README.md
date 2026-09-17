# Verification evidence

## Prerequisites

- Review commit: `4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810`
- API base URL: `https://release-radar-api.diogosouzac.workers.dev/v1`
- Authentication: none

## 1. Health check

```sh
curl --fail --silent --show-error https://release-radar-api.diogosouzac.workers.dev/health
```

Expected response:

```json
{"status":"ok","version":"0.1.0","commit":"4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810"}
```

## 2. Deployment proof

```sh
curl --fail --silent --show-error https://release-radar-api.diogosouzac.workers.dev/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"aridclown-release-radar","commit":"4bbef0e2c7d08e6e4d1140c18fdb5d2507ec7810"}
```

## 3. Capability call

```sh
curl --fail --silent --show-error \
  'https://release-radar-api.diogosouzac.workers.dev/v1/compare?repo=vercel%2Fnext.js&base=v16.4.0-canary.33&head=v16.4.0-canary.34'
```

Expected response shape:

```json
{
  "repo": "vercel/next.js",
  "commitCount": 11,
  "changedFileCount": 140,
  "changedFilesByArea": {"dependencies":24,"configuration":3,"documentation":2,"tests":50,"source":59,"other":2}
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
