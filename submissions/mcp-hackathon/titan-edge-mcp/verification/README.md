# Verification evidence

This document outlines reproducible evidence for Titan Edge MCP Server.

## Prerequisites

- Review commit: `422f0aeb5520a3506b08b05cfefcb76c6cb786c0`
- API base URL: `https://commander-jackhu24.netlify.app/api`
- Authentication: None required for evaluation calls.

## 1. Health check

```bash
curl --fail --silent --show-error https://commander-jackhu24.netlify.app/api/health
```

Expected response:

```json
{
  "status": "ok",
  "commit": "422f0aeb5520a3506b08b05cfefcb76c6cb786c0",
  "service": "titan-edge-mcp"
}
```

## 2. Deployment proof

```bash
curl --fail --silent --show-error https://commander-jackhu24.netlify.app/.well-known/xagent-verification.json
```

Expected response:

```json
{
  "schemaVersion": 1,
  "slug": "titan-edge-mcp",
  "commit": "422f0aeb5520a3506b08b05cfefcb76c6cb786c0"
}
```

## 3. Capability call

```bash
curl --fail --silent --show-error \
  --request POST https://commander-jackhu24.netlify.app/api/titan-edge \
  --header "content-type: application/json" \
  --data '{"action": "diagnose_edge_health"}'
```

Expected response:

```json
{
  "status": "healthy",
  "system": "Titan Edge ASIL-D Redundant MCU",
  "metrics": {
    "heartbeat_ms": 2.1,
    "ftti_margin_pct": 78.5,
    "bus_load_canfd": "18.2%",
    "active_core": "MCU-A Primary",
    "standby_core": "MCU-B Standby",
    "safe_state_ready": true
  },
  "recommendation": "All parameters nominal, zero-fault tolerance state active."
}
```
