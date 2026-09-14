# Verification evidence

## Prerequisites

- Review commit: `ad59479231feefe6d9aa9afc1f7578c49bfbf871`
- API base URL: `https://contract-guard-eta.vercel.app/v1`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://contract-guard-eta.vercel.app/health
```

Expected response:

```json
{"status":"ok","commit":"ad59479231feefe6d9aa9afc1f7578c49bfbf871","service":"contract-guard","version":"1.0.0"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://contract-guard-eta.vercel.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"kestarsheng-contract-guard","commit":"ad59479231feefe6d9aa9afc1f7578c49bfbf871"}
```

## 3. Capability call �?OpenAPI diff (non-breaking change)

```bash
curl --fail --silent --show-error \
  --request POST https://contract-guard-eta.vercel.app/v1/diff \
  --header "content-type: application/json" \
  --data '{"format":"openapi","old_spec":"{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\",\"content\":{\"application/json\":{\"schema\":{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"}}}}}}}}}}}","new_spec":"{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\",\"content\":{\"application/json\":{\"schema\":{\"type\":\"object\",\"properties\":{\"name\":{\"type\":\"string\"},\"email\":{\"type\":\"string\"}}}}}}}}}}}"}'
```

Expected success response:

```json
{
  "schema_version": 1,
  "format": "openapi",
  "breaking": false,
  "total_changes": 1,
  "breaking_count": 0,
  "counts": { "critical": 0, "major": 0, "minor": 0, "info": 1 },
  "summary": "Detected 1 change(s); 0 breaking (1 info).",
  "llm_enabled": false,
  "findings": [
    {
      "change_type": "field_added",
      "breaking": false,
      "severity": "info",
      "location": "GET /users -> response 200.email",
      "summary": "Added field email",
      "source": "confirmed",
      "id": "openapi:field_added:GET /users -> response 200.email"
    }
  ]
}
```

## 4. Capability call �?OpenAPI diff (breaking change)

```bash
curl --fail --silent --show-error \
  --request POST https://contract-guard-eta.vercel.app/v1/diff \
  --header "content-type: application/json" \
  --data '{"format":"openapi","old_spec":"{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"}}}},\"/posts\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"}}}}}}","new_spec":"{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"}}}}}}"}'
```

Expected response (abridged):

```json
{
  "breaking": true,
  "breaking_count": 1,
  "findings": [
    {
      "change_type": "endpoint_removed",
      "breaking": true,
      "severity": "critical",
      "location": "GET /posts",
      "summary": "Removed endpoint GET /posts",
      "source": "confirmed"
    }
  ]
}
```

## 5. Safe error behavior

Invalid format:

```bash
curl --fail --silent --show-error \
  --request POST https://contract-guard-eta.vercel.app/v1/diff \
  --header "content-type: application/json" \
  --data '{"format":"xml","old_spec":"<a/>","new_spec":"<b/>"}'
```

Expected: HTTP 400 with `{"error":"..."}`.

Empty body:

```bash
curl --fail --silent --show-error \
  --request POST https://contract-guard-eta.vercel.app/v1/diff \
  --header "content-type: application/json" \
  --data '{}'
```

Expected: HTTP 422 with validation error detail.