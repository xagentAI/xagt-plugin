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

Add it to any MCP-compatible agent (Claude, Cursor, …) and the agent gains nine tools: `check_breaking_changes`, `list_supported_formats`, `explain_change_type`, `suggest_version_bump`, `generate_changelog`, `suggest_migration`, `scan_consumer_impact`, `check_gate`, `run_benchmark`.

---

## Beyond the diff: consumer-aware impact + verifiable engines

Plain contract diffing is a mature space. Contract Guard goes beyond it with two features classic diff tools (oasdiff, GraphQL Inspector, Redocly, …) do not have:

### 1. Consumer-aware impact scan (`POST /v1/consumer-scan`)

Classic tools answer *“is this change breaking?”* for **every caller**. Contract Guard answers *“is this change breaking **for me**?”* — pass a `consumer_profile` describing only the paths / schemas / fields your agent actually uses, and it separates the findings that hit your subset from the ones you can safely ignore:

```json
{
  "old_spec": "<previous contract>",
  "new_spec": "<new contract>",
  "format": "openapi",
  "consumer_profile": { "paths": ["/pets"], "schemas": ["Pet"] }
}
```

Response includes `consumer_affected`, `hits` (findings that matter to you) and `misses` (ignorable ones).

### 2. Transitive propagation (blast radius)

Changing one referenced component schema can break every operation that returns it. Contract Guard builds the schema→operation reference graph and annotates each finding with its `affected_operations` — a type change on `Pet.id` reports `["GET /pets", "GET /pets/{id}"]`, not just the diff location.

### 3. Self-verification benchmark (`GET /v1/benchmark`)

A built-in 16-sample regression corpus (labelled old/new pairs across all three formats) is replayed through the engines on demand, reporting **accuracy / precision / recall / F1**. The score is deterministic and reproducible — judges can run it themselves.

```
GET /v1/benchmark
→ { "total_samples": 16, "correct": 16, "accuracy": 1.0,
    "precision": 1.0, "recall": 1.0, "f1": 1.0, "results": [...] }
```

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
| `scan_consumer_impact(old_spec, new_spec, format, consumer_profile)` | Consumer-aware scan — which changes affect a specific caller, plus transitive blast radius |
| `check_gate(old_spec, new_spec, format, max_severity, allow_breaking, consumer_profile)` | CI gate — pass/block a contract change against a policy |
| `run_benchmark()` | Replays the 16-sample regression corpus, reports precision/recall/F1 |

### Additional endpoints

| Endpoint | Description |
|---|---|
| `POST /v1/chain-diff` | Multi-version chain analysis (v1→v2→...→vN) |
| `POST /v1/semver` | Suggest SemVer bump from a diff result |
| `POST /v1/migration` | Generate migration suggestions for breaking changes |
| `POST /v1/sarif` | Export diff results as SARIF 2.1.0 for GitHub Code Scanning |
| `POST /v1/changelog` | Generate markdown changelog |
| `POST /v1/consumer-scan` | Consumer-aware impact scan + transitive propagation |
| `POST /v1/gate` | CI gate — pass/block a change against a policy (max_severity / consumer_profile) |
| `GET /v1/benchmark` | Built-in regression corpus — accuracy/precision/recall/F1 |

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
        ├─────────────────────────────────┐
        ▼                                 ▼
  consumer-aware filter           reference graph
  (profile hit / miss)            (schema → operations)
        │                                 │
        ▼                                 ▼
  hits[] + misses[]               affected_operations[]
        │                                 │
        └───────────────┬─────────────────┘
                        ▼
        ImpactReport → JSON (consumer_affected, impact)
        │
        ▼  (optional, if LLM key configured)
  LLM advisory impact assessment
        │
        ▼
  DiffReport → JSON
        │
        ▼
  Regression corpus (16 samples) → /v1/benchmark (P/R/F1)
```

The deterministic engine parses both contracts, walks the schema tree, and emits findings with precise locations (`GET /users -> response 200.email`). `$ref` references are resolved. Constraint tightenings (min/max/pattern/enum) are detected by comparing old vs new ranges. Beyond the diff, `app/impact.py` maps each finding to the consumer subset that uses it and propagates component-schema changes through the schema→operation reference graph; `app/benchmark.py` scores the engines against a built-in labelled corpus.

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

75 tests covering all three engines, orchestration, semver, migration, SARIF, chain diff, consumer-aware impact scan, transitive propagation, the regression benchmark, and the CI gate.

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