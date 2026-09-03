# API

- `GET /health` -> `{status, service, version, commit}`
- `GET /.well-known/xagent-verification.json` -> `{schemaVersion, slug, commit}`
- `POST /v1/sessions` `{resource_type, source, scope, pagination_type, snapshot_strategy}`
- `GET /v1/sessions/{id}` / `GET /v1/sessions/{id}/observations`
- `POST /v1/sessions/{id}/observe` `{page_number, cursor_in, cursor_out, has_more, records_seen, items?, scope?, snapshot_id?, authoritative_total?}` -> `{accepted, coverage_status, next_expected_cursor}`
- `POST /v1/sessions/{id}/failure` `{page_number, kind, message}`
- `POST /v1/sessions/{id}/verify` `{claim:{type, value?, field?, candidate_id?}}` -> `{verdict, blocking_reasons, required_next_actions, certified_value?, certificate?}`
- `GET /v1/sessions/{id}/certificate`
- `POST /v1/claims/parse` `{text}` -> `{type, resource, scope|field, value?}`
