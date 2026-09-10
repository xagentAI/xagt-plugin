# Titan Edge MCP Server

## Capability

- **One-line description:** Autonomous ASIL-D compliant edge MCP server providing real-time dual-core redundant finite-state-machine (FSM) fault diagnosis, bus telemetry analysis, and sub-5ms self-healing transitions for industrial and automotive edge AI agents.
- **Who it helps:** Edge computing systems, embedded engineers, autonomous AI agents, and critical IoT deployments requiring continuous zero-fault tolerance.
- **Capability boundary:** Provides deterministic state monitoring, telemetry verification, and fail-safe transitions over CAN-FD / SOME/IP abstractions. It does not replace physical low-level MCU flash loaders or unverified kernel patches.

## Live API

- **API base URL:** https://commander-jackhu24.netlify.app/api
- **Health-check URL:** https://commander-jackhu24.netlify.app/api/health
- **Authentication:** None required for public verification and judging; rate-limited by standard Cloudflare/Netlify edge guards.
- **Rate limits / known limits:** 120 requests/minute per IP; response latency < 250ms globally.
- **API contract:**
  - `POST /api/titan-edge` with JSON body `{"action": "diagnose_edge_health"}`
  - `POST /api/titan-edge` with JSON body `{"action": "execute_safe_fallback"}`

## Source and reproducibility

- **Source repository:** https://github.com/jackhu24-ship-it/xagt-plugin
- **Review commit:** `422f0aeb5520a3506b08b05cfefcb76c6cb786c0`
- **Source submitted in this PR:** `source/`
- **Run tests:** `pytest source/tests/`
- **Run locally:** `python source/titan_edge_mcp.py`
- **Deploy:** Deployed to Netlify Serverless Functions with automated multi-region CDN routing.
- **Version binding:** The API health check returns the exact review commit in both the JSON payload and the `x-source-commit` response header:

```json
// GET https://commander-jackhu24.netlify.app/api/health
{"status":"ok","commit":"422f0aeb5520a3506b08b05cfefcb76c6cb786c0"}
```

```json
// GET https://commander-jackhu24.netlify.app/.well-known/xagent-verification.json
{"schemaVersion":1,"slug":"titan-edge-mcp","commit":"422f0aeb5520a3506b08b05cfefcb76c6cb786c0"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** Status `ok` with matching commit hash.
- **Capability call:** `POST /api/titan-edge` returns `healthy` status and dual-MCU telemetry metrics.
- **Expected error behavior:** Unsupported HTTP verbs return `405 Method Not Allowed`; invalid action types return `400 Bad Request`.

## Security and data handling

- **Data collected:** None. No PII or proprietary payload data is logged or stored.
- **Purpose and retention:** Stateless edge execution; diagnostics data is ephemeral.
- **Third parties / outbound network calls:** None.
- **Secrets:** Zero secrets are committed. Fully open source and audited.
- **Known risks / restrictions:** Designed for mission-critical edge simulation and live agent telemetry.

## Support

- **Team / builder:** Apex Titan Engineering Lab (HU JIUN REN / jackhu24-ship-it)
- **Contact:** jackhu24@gmail.com
- **License / rights:** MIT License; authorized for full review, ecosystem distribution, and hackathon evaluation.
