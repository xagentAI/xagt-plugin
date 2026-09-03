# API

- `GET /health` -> `{status, service, version}`
- `GET /.well-known/xagent-verification.json` -> `{schemaVersion, slug, commit}`
- `POST /api/projects` `{name, openapi_url?, openapi_json?}`
- `POST /api/projects/upload` form `{name, file}`
- `GET /api/projects` / `GET /api/projects/{id}`
- `POST /api/projects/{id}/analyze` / `GET /api/projects/{id}/analysis`
- `POST /api/projects/{id}/test` / `GET /api/projects/{id}/tests`
- `GET /api/projects/{id}/issues` / `GET /api/projects/{id}/score`
- `POST /api/projects/{id}/repair` / `GET /api/projects/{id}/repairs`
- `POST /api/projects/{id}/retest`
- `GET /api/projects/{id}/tools`
- `POST /api/projects/{id}/proxy/{operation_id}` `{arguments:{...}}`
- `GET /api/projects/{id}/export`

Errors: `INVALID_ARGUMENT, UPSTREAM_TIMEOUT, UPSTREAM_RATE_LIMIT, UPSTREAM_AUTH_ERROR, UPSTREAM_SERVER_ERROR, INVALID_UPSTREAM_RESPONSE, SCHEMA_VALIDATION_FAILED, TRANSFORMATION_FAILED`.
