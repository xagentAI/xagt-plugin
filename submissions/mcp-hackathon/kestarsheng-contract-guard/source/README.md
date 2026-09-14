# Contract Guard

**Deterministic API breaking-change detector for AI agents.**

English | [中文](README_ZH.md)

Contract Guard gives any AI agent the ability to judge whether an API change is safe or breaking — without guessing. It compares two versions of an OpenAPI, GraphQL, or JSON Schema contract and returns structured, reproducible findings in milliseconds. The core diff engine is 100% deterministic and works offline; an optional LLM advisory layer can append consumer-impact context when a key is configured.

> **Why not just ask the LLM?** LLMs hallucinate schema diffs, miss nested constraint tightenings, and can't guarantee the same answer twice. Contract Guard's rule engine is built for the exact job: every input pair produces the same finding set, every time.

---

## Quick start

**Live demo:** <https://contract-guard-eta.vercel.app>

**REST API:**

```bash
curl -X POST https://contract-guard-eta.vercel.app/v1/diff \
  -H "Content-Type: application/json" \
  -d '{
    "format": "openapi",
    "old_spec": "{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"}}}}}}",
    "new_spec": "{\"openapi\":\"3.0.0\",\"paths\":{\"/users\":{\"get\":{\"responses\":{\"200\":{\"description\":\"ok\"},\"404\":{\"description\":\"not found\"}}}}}}"
  }'
```

**MCP endpoint:** `https://contract-guard-eta.vercel.app/mcp`

Add it to any MCP-compatible agent (Claude, Cursor, …) and the agent gains six tools: `check_breaking_changes`, `list_supported_formats`, `explain_change_type`, `suggest_version_bump`, `generate_changelog`, `suggest_migration`.

---

## What it detects

### OpenAPI 3.x

| Change | Severity | Breaking |
|---|---|---|
| Endpoint / method removed | critical | yes |
| Required parameter added | critical | yes |
| Parameter removed | major | yes |
| Optional → required parameter | major | yes |
| Response status removed | critical | yes |
| Schema / field removed | critical | yes |
| Field type changed | critical | yes |
| Enum value removed | critical | yes |
| Constraint tightened (min/max/pattern) | major | yes |
| Required field added | critical | yes |
| Content-Type removed/changed | critical | yes |
| Field/endpoint deprecated | info | no |
| New endpoint / field added | info | no |

### GraphQL SDL

| Change | Severity | Breaking |
|---|---|---|
| Type removed / kind changed | critical | yes |
| Field removed / type changed | critical | yes |
| Nullable → non-null | critical | yes |
| Argument removed / required arg added | critical | yes |
| Input field removed / required input field added | critical | yes |
| Union member removed | critical | yes |
| Directive removed | major | yes |
| `@deprecated` added | info | no |

### JSON Schema

| Change | Severity | Breaking |
|---|---|---|
| Property removed / type changed | critical | yes |
| `const` value changed | critical | yes |
| Required property added | critical | yes |
| Enum value removed | critical | yes |
| Constraint tightened | major | yes |
| `additionalProperties` restricted | major | yes |
| `prefixItems` (tuple) changed | critical | yes |
| `dependentRequired` added | major | yes |
| `unevaluatedProperties` restricted | major | yes |

---

## API reference

### `POST /v1/diff`

Compare two contracts and return a structured breaking-change report.

```json
{
  "format": "openapi",
  "old_spec": "<previous contract text>",
  "new_spec": "<new contract text>",
  "use_llm": false
}
```

Response:

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
      "previous": null,
      "current": null,
      "suggestion": "",
      "source": "confirmed",
      "id": "openapi:field_added:GET /users -> response 200.email"
    }
  ]
}
```

Each finding has `source: "confirmed"` (deterministic engine) or `source: "advisory"` (optional LLM layer).

### `GET /health`

```json
{ "status": "ok", "commit": "92814ad…", "service": "contract-guard", "version": "1.0.0" }
```

### `GET /.well-known/xagent-verification.json`

```json
{ "schemaVersion": 1, "slug": "contract-guard", "commit": "92814ad…" }
```

### `GET /v1/formats`

Lists supported contract formats.

### MCP tools

| Tool | Description |
|---|---|
| `check_breaking_changes(old_spec, new_spec, format, use_llm)` | Core diff — returns full finding report as JSON string |
| `list_supported_formats()` | Instant, free — lists accepted formats |
| `explain_change_type(change_type)` | Instant, free — explains what a change_type means |
| `suggest_version_bump(old_spec, new_spec, format, current_version)` | Suggests SemVer bump level (major/minor/patch) |
| `generate_changelog(old_spec, new_spec, format, old_version, new_version)` | Generates markdown changelog for release notes |
| `suggest_migration(old_spec, new_spec, format)` | Generates compatibility migration suggestions for breaking changes |

### Additional endpoints

| Endpoint | Description |
|---|---|
| `POST /v1/chain-diff` | Multi-version chain analysis (v1→v2→...→vN) |
| `POST /v1/semver` | Suggest SemVer bump from a diff result |
| `POST /v1/migration` | Generate migration suggestions for breaking changes |
| `POST /v1/sarif` | Export diff results as SARIF 2.1.0 for GitHub Code Scanning |
| `POST /v1/changelog` | Generate markdown changelog |

---

## Architecture

```
old_spec + new_spec
        │
        ▼
  normalize_format()        ← accepts aliases: swagger, oas, gql, jsonschema, json
        │
        ▼
  ┌─────────────────────────────────┐
  │  Deterministic diff engine      │
  │  (zero LLM, fully reproducible) │
  │                                 │
  │  OpenAPI  │ GraphQL │ JSON Schema│
  └─────────────────────────────────┘
        │
        ▼
  Finding[]  (source: "confirmed")
        │
        ▼  (optional, if LLM key configured)
  LLM advisory impact assessment
        │
        ▼
  Finding[]  (source: "advisory")
        │
        ▼
  DiffReport → JSON
```

The deterministic engine parses both contracts, walks the schema tree, and emits findings with precise locations (`GET /users -> response 200.email`). `$ref` references are resolved. Constraint tightenings (min/max/pattern/enum) are detected by comparing old vs new ranges.

---

## Run locally

```bash
git clone https://github.com/kestarsheng/contract-guard.git
cd contract-guard
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Open <http://localhost:8000> for the demo page, <http://localhost:8000/docs> for Swagger.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `COMMIT` | `dev` | Git commit hash (set by deployment) |
| `LLM_API_KEY` | (empty) | Optional — enables advisory LLM layer |
| `LLM_BASE_URL` | `https://api.deepseek.com/v1` | OpenAI-compatible endpoint |
| `LLM_MODEL` | `deepseek-chat` | Model name |
| `MAX_SPEC_CHARS` | `200000` | Max input size per spec |

---

## Tests

```bash
pytest -v
```

46 tests covering all three engines, orchestration, semver, migration, SARIF, and chain diff.

---

## Tech stack

- **FastAPI** — REST API + Swagger docs
- **FastMCP 4.0.3** — MCP server (streamable HTTP, mounted at `/mcp`)
- **graphql-core 3.2** — GraphQL SDL parsing
- **PyYAML** — YAML OpenAPI support
- **Vercel** — serverless deployment (Python 3.12)

---

## License

MIT