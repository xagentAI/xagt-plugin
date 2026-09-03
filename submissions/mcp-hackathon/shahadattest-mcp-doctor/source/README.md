# MCP Doctor

**MCP Doctor turns messy or unreliable APIs into consistent, validated, agent-ready tools.**

Give MCP Doctor an API. It tests the API, finds what makes it unreliable for AI agents, creates a normalized compatibility layer, validates the repaired interface, and generates an agent-ready tool.

> Postman tests APIs. MCP Doctor prepares them for AI agents.

## How it works

Import → Test → Diagnose → Repair → Agentize → Retest → Generate tool. Before/after readiness score is the hero moment (e.g. 43 → 96).

## Quick start (local)

```bash
cd mcp-doctor/backend
pip install -r requirements.txt
python -m uvicorn app.main:app --port 8000
# demo api
cd ../examples/broken-demo-api
python -m uvicorn main:app --port 8001
# open ../frontend/index.html (set backend http://localhost:8000)
```

Set `ALLOW_PRIVATE_NETWORK=true` for local demo testing against localhost.

## Docker

```bash
cd mcp-doctor
docker-compose up --build
# frontend http://localhost:3000 backend http://localhost:8000/health demo http://localhost:8001/health
```

## API examples

```bash
curl http://localhost:8000/health
curl -X POST http://localhost:8000/api/projects -H 'Content-Type: application/json' -d '{"name":"Demo","openapi_url":"http://demo-api:8001/openapi.json"}'
```

## Project structure

See `docs/architecture.md`. Backend `backend/app/services/*`, demo `examples/broken-demo-api`, dashboard `frontend/`.

## Security

SSRF guard, timeout/retry, size limits, safe-method-only auto-test, no codegen execution, secrets via env. This is a compatibility tool, not a vulnerability scanner.

## Limitations / Future

Static dashboard (Next.js port later), repair simulation scoring, single-table SQLite, no auth/billing yet. Roadmap: drift detection, monitoring, self-healing adapters, MCP server export, pay-per-call.

## License

MIT (see LICENSE).
