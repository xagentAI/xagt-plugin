# Verification evidence

## Prerequisites

- Review commit: `3ce175fb14a0e176a9b29a2c213d78d4fab91bad`
- API base URL: `https://belts-raymond-advertisements-radical.trycloudflare.com/api` (local: `http://localhost:8000/api`)
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://belts-raymond-advertisements-radical.trycloudflare.com/health
```

Expected response:

```json
{"status":"ok","service":"mcp-doctor","version":"0.1.0","commit":"3ce175fb14a0e176a9b29a2c213d78d4fab91bad"}
```

Local evidence (container `mcp-doctor-backend-1`, verified 2026-09-04):

```json
{"status":"ok","service":"mcp-doctor","version":"0.1.0","commit":"3ce175fb14a0e176a9b29a2c213d78d4fab91bad"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://belts-raymond-advertisements-radical.trycloudflare.com/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"shahadattest-mcp-doctor","commit":"3ce175fb14a0e176a9b29a2c213d78d4fab91bad"}
```

## 3. Capability call

Create a project from the bundled demo spec (`source/examples/broken-demo-api/openapi-demo.json`):

```bash
curl --fail --silent --show-error --request POST https://belts-raymond-advertisements-radical.trycloudflare.com/api/projects \
  --header "content-type: application/json" \
  --data '{"name":"Demo Weather API","openapi_json":{...demo spec...}}'
```

Expected success (local evidence): `{"id":"<pid>","name":"Demo Weather API","endpoints":4}`.
Then `POST /api/projects/<pid>/analyze` → readiness `62/100` with issues
(`NO_RESPONSE_SCHEMA`, `NO_4XX_DOC`, `AMBIGUOUS_PARAM`);
`POST /api/projects/<pid>/test` → 4 passed;
`POST /api/projects/<pid>/repair` → 5 declarative rules;
`POST /api/projects/<pid>/proxy/getWeather` with `{"arguments":{}}` →
`{"success":true,"operation":"getWeather","data":{"temperature_celsius":31,"condition":"sunny",...}}`.

Safe failure example — invalid spec:

```bash
curl --request POST https://belts-raymond-advertisements-radical.trycloudflare.com/api/projects \
  --header "content-type: application/json" --data '{"name":"Bad"}'
```

Expected: HTTP 400 `Provide openapi_url or openapi_json`.
