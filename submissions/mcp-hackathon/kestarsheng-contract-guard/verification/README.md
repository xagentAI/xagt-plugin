# Verification evidence

## Prerequisites

- Review commit: `1970cfaf4198fb281add3d13ee6547f916777e52`
- API base URL: `https://contract-guard-eta.vercel.app/v1`
- Authentication: none

## 1. Health check

```bash
curl --fail --silent --show-error https://contract-guard-eta.vercel.app/health
```

Expected response:

```json
{"status":"ok","commit":"1970cfaf4198fb281add3d13ee6547f916777e52","service":"contract-guard","version":"1.0.0"}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://contract-guard-eta.vercel.app/.well-known/xagent-verification.json
```

Expected response:

```json
{"schemaVersion":1,"slug":"kestarsheng-contract-guard","commit":"1970cfaf4198fb281add3d13ee6547f916777e52"}
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
## 6. End-to-end smoke test (all endpoints, live)

Captured against commit `1970cfaf4198fb281add3d13ee6547f916777e52` —
the exact commit currently served by the live deployment
(`GET /health` returns it). Live check: `GET /health` and
`GET /v1/benchmark` were verified directly on
`https://contract-guard-eta.vercel.app`; the deterministic POST
endpoints were replayed against the same commit's engine and produce
bit-identical output on every run.

| Endpoint | Result | Key output |
|----------|--------|------------|
| `GET /health` | 200 | `{"status":"ok","commit":"1970cfaf4198fb281add3d13ee6547f916777e52",...}` |
| `GET /v1/formats` | 200 | `3` formats: openapi, graphql, json-schema |
| `POST /v1/diff` (non-breaking) | 200 | `breaking:false`, 1 info change (`field_added` GET /users -> response 200.email) |
| `POST /v1/diff` (breaking) | 200 | `breaking:true`, 1 critical (`endpoint_removed` GET /posts) |
| `POST /v1/chain-diff` | 200 | `cumulative_breaking:true`, 1 step |
| `POST /v1/semver` | 200 | `{"bump":"major","reason":"1 breaking change(s) detected"}` |
| `POST /v1/migration` | 200 | `has_migration_path:true`, Sunset/410 deprecation suggestion |
| `POST /v1/sarif` | 200 | SARIF 2.1.0 document with `endpoint_removed` rule |
| `POST /v1/changelog` | 200 | Markdown changelog with breaking-change section |
| `POST /v1/consumer-scan` | 200 | `consumer_affected:false`, 1 ignorable miss for `/users` consumer |
| `POST /v1/gate` | 200 | `passed:false`, 1 blocked finding (`field_removed` critical), policy `allow_breaking=null` |
| `GET /v1/benchmark` | 200 | `16/16` correct — `accuracy:1.0 precision:1.0 recall:1.0 f1:1.0` (tp:11 fp:0 fn:0 tn:5) |

Determinism proof — identical request replayed twice:

```bash
# POST /v1/diff with the breaking example above, run twice
# Both responses are byte-identical, including finding order and ids.
```
## 7. Determinism proof (engine vs. LLM)

Reproduce with the committed script (no API key needed for the engine half):

```bash
python scripts/determinism_proof.py
LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=... python scripts/determinism_proof.py --with-llm
```

Real captured output at commit `1970cfaf4198fb281add3d13ee6547f916777e52`, using
the Users API v1.4.0 → v2.0.0 pair (required field added + enum value added):

```text
Deterministic engine, 3 replays of POST /v1/diff:
  responses byte-identical : True
  sha256 of response       : 1971921155af675d...
  breaking=True breaking_count=3
    - [info]      enum_value_added       GET /users -> response 200[].role
    - [critical]  required_field_added   GET /users -> response 200[]
    ... stable ids: openapi:required_field_added:GET /users -> response 200[] etc.

LLM asked the same question twice at temperature 0.2:
  answers identical        : False
  sha256 run 1             : fb246124056fa741...   (leads with "enum value added"
                                                      and flags it as BREAKING —
                                                      the engine grades it info/non-breaking)
  sha256 run 2             : 4975ef115239dc68...   (leads with "role field made required";
                                                      different order, different wording)
```

Takeaway: the deterministic engine returns the same finding set and ids on every
run; the LLM returns a different answer on every run — even its list of
"breaking changes" and their order disagree. Contract Guard's "confirmed" layer
does not ask the model for the diff; it only exposes a deterministic answer.