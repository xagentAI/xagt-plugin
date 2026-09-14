# Contract Guard

## Capability

- **One-line description:** Deterministic API breaking-change detector for AI agents �?compares two OpenAPI / GraphQL / JSON Schema contracts and returns structured, reproducible findings with zero LLM dependency in the core diff.
- **Who it helps:** Any AI agent that needs to judge whether an API change is safe or breaking before merging, publishing, or upgrading a dependency. Also useful for developers and CI pipelines that want a deterministic compatibility gate.
- **Capability boundary:** Accepts two contract texts (old + new) as strings in OpenAPI 3.x (JSON/YAML), GraphQL SDL, or JSON Schema (draft-07 / 2020-12) format, plus a format identifier and optional `use_llm` flag. Max input 200 000 chars per spec. Returns a JSON report with `breaking` (bool), `breaking_count`, `total_changes`, per-severity counts, and a `findings[]` array where each finding has `change_type`, `breaking`, `severity` (critical/major/minor/info), `location`, `summary`, `source` ("confirmed" for deterministic engine, "advisory" for optional LLM layer), and `id`. The deterministic engine covers 35+ change types across three formats including content-type changes, deprecation detection, GraphQL directive changes, and JSON Schema 2020-12 keywords (prefixItems, contains, dependentRequired, unevaluatedProperties). Also provides 8 MCP tools (`check_breaking_changes`, `list_supported_formats`, `explain_change_type`, `suggest_version_bump`, `generate_changelog`, `suggest_migration`, `scan_consumer_impact`, `run_benchmark`), 8 REST endpoints (`POST /v1/diff`, `POST /v1/chain-diff`, `POST /v1/semver`, `POST /v1/migration`, `POST /v1/sarif`, `POST /v1/changelog`, `POST /v1/consumer-scan`, `GET /v1/benchmark`), SARIF 2.1.0 export for GitHub Code Scanning, consumer-aware impact scan (separates findings that hit a specific caller's subset from ignorable ones), transitive propagation (annotates each finding with affected operations via schema->operation reference graph), a 16-sample regression benchmark corpus with precision/recall/F1 scoring, and an 8-tab interactive demo workbench covering all eight REST endpoints (breaking diff, chain diff, SemVer, migrations, SARIF, changelog, consumer-aware impact scan, regression benchmark). Does not execute code, call external APIs (unless LLM advisory enabled), or persist submitted contracts.

## Live API

- **API base URL:** https://contract-guard-eta.vercel.app/v1
- **Health-check URL:** https://contract-guard-eta.vercel.app/health
- **Authentication:** none
- **Rate limits / known limits:** Max spec size 200 000 chars per request. Vercel serverless 10 s timeout �?sufficient for all deterministic diffs. LLM advisory layer (optional) may add latency.
- **API contract:** OpenAPI at `/docs`; request `POST /v1/diff` body `{"format": "openapi|graphql|json-schema", "old_spec": string, "new_spec": string, "use_llm"?: bool}`, response `{"schema_version": 1, "format": string, "breaking": bool, "total_changes": int, "breaking_count": int, "counts": {...}, "summary": string, "llm_enabled": bool, "findings": [...]}`. Additional endpoints: `POST /v1/chain-diff` (multi-version analysis), `POST /v1/semver` (SemVer bump), `POST /v1/migration` (migration suggestions), `POST /v1/sarif` (SARIF export), `POST /v1/changelog` (markdown changelog), `POST /v1/consumer-scan` (consumer-aware impact scan + transitive propagation), `GET /v1/benchmark` (regression corpus precision/recall/F1). MCP endpoint at `/mcp` with 8 tools. Demo page at `GET /`.

## Source and reproducibility

- **Source repository:** https://github.com/kestarsheng/contract-guard
- **Review commit:** `ad59479231feefe6d9aa9afc1f7578c49bfbf871`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pip install -r requirements.txt && pytest tests/ -v`
- **Run locally:** `pip install -r requirements.txt && uvicorn app.main:app --reload`
- **Deploy:** Vercel (current production deployment). Set `COMMIT` env var to the git commit hash.
- **Version binding:** `GET /health` returns `{"status":"ok","commit":"<commit>","service":"contract-guard","version":"1.0.0"}`; `GET /.well-known/xagent-verification.json` returns `{"schemaVersion":1,"slug":"kestarsheng-contract-guard","commit":"<commit>"}`. The commit is injected via the `COMMIT` environment variable at deploy time.

The API must expose:

```json
// GET /health
{"status":"ok","commit":"ad59479231feefe6d9aa9afc1f7578c49bfbf871","service":"contract-guard","version":"1.0.0"}
```

```json
// GET /.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"kestarsheng-contract-guard","commit":"ad59479231feefe6d9aa9afc1f7578c49bfbf871"}
```

## Verification

The reproducible call instructions and example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","commit":"ad59479231feefe6d9aa9afc1f7578c49bfbf871","service":"contract-guard","version":"1.0.0"}`
- **Capability call:** `POST /v1/diff` with `{"format":"openapi","old_spec":"...","new_spec":"..."}`
- **Expected error behavior:** Invalid format �?400; oversized spec �?413; malformed JSON �?422.

## Security and data handling

- **Data collected:** Two contract texts (old + new) and a format identifier. No authentication, no user identifiers.
- **Purpose and retention:** Contracts are parsed in memory for diff computation only. The service does not persist submitted contracts to any database or log. If LLM advisory is enabled, contract excerpts may be sent to the configured LLM provider.
- **Third parties / outbound network calls:** None in default mode (deterministic engine only). Optional LLM advisory calls an OpenAI-compatible API (DeepSeek) if `LLM_API_KEY` is configured.
- **Secrets:** No secrets are committed. `LLM_API_KEY` is set as a deployment environment variable and never appears in source.
- **Known risks / restrictions:** Vercel serverless functions have a 10 s timeout; the deterministic engine completes well within this limit. The optional LLM advisory layer may timeout on very large specs.

## Support

- **Team / builder:** kestarsheng (刘宇�?
- **Contact:** 2410251355@henu.edu.cn
- **License / rights:** MIT �?submission for X-Agent AI MCP Hackathon 2026. Submitter owns all source and authorizes review and post-award retention.