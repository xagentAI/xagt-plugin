# MCPForge — Turn any OpenAPI API into agent-ready, billable MCP tools

**X-Agent AI MCP Hackathon 2026 · Open Innovation track**

MCPForge reads an OpenAPI description — URL, local file, or pasted text — and produces MCP tools an agent can call, verify, and pay for. It runs the full chain the hackathon asks for: **Build → Verify → MCPize → Monetize**.

---

## Live deployment

| Endpoint | Value |
|---|---|
| Base URL | https://mcpforge-cypewake.app.workbuddy.host |
| Health (hard gate) | https://mcpforge-cypewake.app.workbuddy.host/api/health |
| Deployment proof | https://mcpforge-cypewake.app.workbuddy.host/.well-known/xagent-verification.json |
| MCP endpoint | https://mcpforge-cypewake.app.workbuddy.host/mcp/ |
| Pinned review commit | `3db59e3afed8e1de2929197dc107b328701d7a22` |

Both proof endpoints return the pinned commit above, and the deployed code is byte-identical to that commit in the public fork.

---

## What a reviewer can check in one command

```bash
pip install -r requirements.txt
python docs/judge_check.py      # 11/11 checks, exits 0
pytest                          # 53 offline tests
pytest -m live -v               # 6 live tests against public APIs
```

Every claim below maps to a command or a file in this repository.

| Judge question | Evidence | Reproduce |
|---|---|---|
| Is the wrapped API real? | Live demo calls the JSONPlaceholder (default) and GitHub (opt-in) public REST APIs and returns 2xx on showcase operations | `python docs/judge_check.py` |
| Is it callable? | 14 MCP tools enumerate over `/mcp` with a stock `fastmcp.Client` | same run, tools section |
| Is it verifiable? | `verify_api` counts **only HTTP 2xx** as passed; 401/403/404/429/5xx are classified separately | `core.classify_response` + tests |
| Is it monetizable? | Per-call metering persisted to `usage.json` (atomic write), then billed by tier | `examples/real_showcase_result.json` |

---

## The real task: why this is more than a spec converter

Scoring weights "real agent or user value" highest. A converter that generates tools proves plumbing. MCPForge finishes a task that a prompt alone cannot, because the answer depends on live numbers.

The live demo (`POST /api/real-task`, default **JSONPlaceholder**) runs a real three-step chain against a public REST API:

1. **List** — pull recent posts from JSONPlaceholder.
2. **Verify each** — fetch each post and its author back at the source, because list summaries go stale.
3. **Aggregate** — rank by author and surface a reading brief (top author, company, post count).

JSONPlaceholder is the default because the deployment egress allows it; GitHub is blocked there. The same handler accepts `{"api":"github"}` to run the GitHub sample live wherever egress is normal, and a recorded GitHub run is kept at `examples/real_agent_task_result.json`.

Result from the recorded run (`examples/real_agent_task_result.json`):

| Rank | Repository | Stars | Language |
|---|---|---:|---|
| 1 | `modelcontextprotocol/servers` | 90,384 | TypeScript |
| 2 | `HKUDS/nanobot` | 48,216 | Python |

Star counts and push timestamps change daily, so a model answering from memory gives wrong numbers. The live JSONPlaceholder chain likewise returns numbers only a real call can produce. Every step also records metering and billing: the actual run metered 24 calls, and the same pricing model projects **$7,600 USD per month at 1,000,000 calls** (pro tier: 50,000 calls included, $8.00 per additional 1,000).

Run it yourself:

```bash
python examples/real_agent_task.py
```

---

## The 14 tools

Seven names come straight from the delivery spec (bold); the rest carry the four stages end to end.

| Tool | Stage | What it does |
|---|---|---|
| **`parse_openapi_spec`** | Build | Resolves `$ref`, merges path-level with operation-level parameters, detects auth schemes and pagination |
| **`list_operations`** | Build | Human-readable inventory, flagged by "needs auth / paginated / deprecated" |
| **`call_rest_api`** | Build | Generic REST call with SSRF protection |
| `verify_api` | Verify | Concurrent real calls; **2xx is the only pass**; supports scope filtering first |
| **`generate_mcp_tool_code`** | MCPize | One operation → deployable FastMCP tool source with retry and auth |
| `generate_mcp_bundle` | MCPize | Full deployable package, writes to disk under a path allowlist; supports scope curation |
| `preview_scope` | MCPize | Previews curation: endpoints before vs. tools after, recommended dimensions |
| `build_manifest` | Monetize | Listing payload: per-tool `input_schema`, auth requirements, tiers and quotas |
| `usage_report` | Monetize | Real usage: totals, success rate, per-operation counts and latency |
| `simulate_invoice` | Monetize | Bills by tier: quota, overage, unit price, amount due, per-operation lines |
| `register_api_from_spec` | Core | Registers a spec (atomic write, survives restart) |
| **`call_registered_api`** | Core | Calls by `operation_id`, metered; accepts flat params or a `params` object |
| `list_registered_apis` | Core | Lists registered APIs and their auth schemes |
| **`health_check`** | Core | Liveness probe |

---

## Where this differs from the usual OpenAPI→MCP generator

| Stage | What MCPForge does | What the common implementation does |
|---|---|---|
| Build | Real parsing: `$ref` expansion, path-level parameter merge, auth and pagination detection, OpenAPI 2.0 and 3.x | Reads `operationId` and `path`; drops fields on `$ref` or Swagger 2.0 |
| Verify | Status-code truth table: 2xx pass, 401/403 need auth, 404 missing, 429 rate-limited, other 4xx bad params, network failure unreachable | Treats any HTTP response as "callable", so 404 and 500 go green and the metric means nothing |
| MCPize | Generates runnable packages: URL built from a template with `str.replace`, escaped docstrings, de-duplicated function names, 3 retries, pinned version line | Interpolates raw paths into f-strings, so `{account-id}` produces `NameError` |
| Monetize | Meters every call to disk, reports usage, bills by tier, projects the observed daily rate to 30 days | Prints a price table; no metering, no invoice |

### Tool curation: the tool-explosion fix

A 100-endpoint spec exported naively becomes 100 tools, which floods the context window and degrades tool selection. MCPForge v2.1 puts a scope layer in the generation path:

```python
{
  "include_tags": ["pet"],
  "include_methods": ["GET"],
  "include_path_patterns": ["/pet/*"],
  "exclude_deprecated": True,
  "intent": "user account",
  "top_n": 5
}
```

On Swagger Petstore: 19 endpoints → 3 tools at 84% reduction with tag+method filtering, or 5 tools by intent.

---

## Security boundaries (on by default)

| Boundary | Default | How to relax |
|---|---|---|
| Local spec reads | Restricted to the working directory | `MCPFORGE_READ_ROOTS`, or `MCPFORGE_ALLOW_ANY_PATH=1` |
| Generated output | Name allowlist; result must land inside the output root | — |
| Outbound requests | Blocks loopback, private ranges, link-local, reserved addresses, and cloud metadata endpoints; **re-validated on every redirect hop** | `MCPFORGE_ALLOW_PRIVATE_NET=1` |
| Outbound trusted hosts | Block all hosts by default; the operator may pin specific public showcase hosts (e.g. `api.github.com`) that a cloud egress proxies into a reserved range (198.18.0.0/15). Only the named host is exempt; every other URL still goes through the full check. The live demo targets JSONPlaceholder, which the same egress allows and needs no pin | `MCPFORGE_TRUSTED_HOSTS=api.github.com` |
| Metering and registry | Atomic writes; a corrupt file is preserved as `.corrupt.json`, never silently cleared | — |

### The redirect bypass, and why it gets its own section

`httpx` with `follow_redirects=True` validates **only the initial URL**. A public URL that answers 302 to `http://127.0.0.1:8000/` or `http://169.254.169.254/latest/meta-data/` passes the first check and then walks straight into the private network. We reproduced it locally against a public redirector and a local service:

```
== bypass attempt: public URL 302 to internal ==
  status_code = 200
  final url   = http://127.0.0.1:8123/
  >>> read internal content
```

`core.request_with_validated_redirects()` follows hops manually, re-checking each one, applies the 302/303 method rewrite per RFC, and caps redirect loops. Four regression cases lock it down: private target, metadata target, legitimate cross-origin redirect not broken, redirect loop exits.

---

## One documented deviation from the spec

The spec asks for `call_registered_api(name, operation_id, **params)`. FastMCP 4.0.3 refuses to register a `**kwargs` tool:

```
ValueError: Functions with **kwargs are not supported as tools
```

Both usual workarounds fail too — `Tool.from_function(parameters=...)` and `@mcp.tool(parameters=...)` raise `TypeError: unexpected keyword argument 'parameters'`.

`fastmcp_kwargs.py` solves it by subclassing `fastmcp.tools.Tool`, whose `run()` is overridable, and declaring `additionalProperties: true` in an explicit `inputSchema`. Both call shapes pass over the real protocol stack:

```json
{"name":"petstore","operation_id":"getPetById","petId":1}
{"name":"petstore","operation_id":"getPetById","params":{"petId":1}}
```

The override touches parameter encode/decode for one tool and nothing else.

---

## Run it

```bash
pip install -r requirements.txt

# One process, one port: walkthrough page + health + MCP endpoint
python app.py                  # http://localhost:8000

# MCP server only
fastmcp dev server.py
fastmcp run server.py --transport streamable-http --port 8080

# Container
docker build -t mcpsforge . && docker run -p 8000:8000 -v mcpsforge-data:/data mcpsforge
```

Verify with any MCP client:

```python
import asyncio
from fastmcp import Client

async def main():
    async with Client("https://mcpforge-cypewake.app.workbuddy.host/mcp/") as c:
        print([t.name for t in await c.list_tools()])
        print((await c.call_tool("health_check", {})).data)
        print((await c.call_tool("call_rest_api", {
            "base_url": "https://api.github.com", "path": "/zen", "method": "GET",
        })).data["status_code"])

asyncio.run(main())
```

---

## Layout

```
api-mcp-toolkit/
├── server.py              # FastMCP server, 14 tools mapped to the four stages
├── core.py                # Parse, verify, generate, manifest, registry, scope curation
├── metering.py            # Usage and billing, atomic usage.json, monthly projection
├── fastmcp_kwargs.py      # **kwargs tool support, with the measured evidence above
├── demo_app.py            # Walkthrough page + mounted /mcp + health + proof endpoints
├── app.py                 # Deployment entrypoint, reads PORT, binds 0.0.0.0
├── verify.py              # Two-layer acceptance, writes verification-evidence.md
├── static/index.html      # Walkthrough UI
├── docs/                  # judge_check.py, evidence, market and product notes
├── tests/                 # 53 offline + 6 live tests, offline fixtures
├── examples/              # Generated bundles and the real-task script
└── Dockerfile, requirements*.txt, pyproject.toml
```

---

## Compliance

- Generic API and MCP engineering. No vulnerability detection, risk scoring, phishing or fraud detection, security monitoring, compliance analysis, or on-chain security surface — the disqualifying categories do not apply.
- The SSRF guard in `verify_api` and `call_rest_api` protects the tool as an HTTP client: it refuses to send requests to loopback, private ranges, or cloud metadata. It produces no security assessment, score, or alert.
- Invoices default to `USD` (override with `MCPFORGE_CURRENCY`). This is an engineering portfolio piece and takes no position in any token.
