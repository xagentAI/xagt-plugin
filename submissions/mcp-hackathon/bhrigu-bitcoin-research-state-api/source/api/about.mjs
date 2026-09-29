import { methodGate, sendJson } from "../lib/http.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  sendJson(res, 200, {
    name: "BHRIGU Bitcoin Temporal Evidence",
    capability: "read-only precommit → reality → memory for Bitcoin research",
    endpoint: "/v1/state",
    windows: "/v1/windows",
    mcp: "/mcp",
    openapi: "/openapi.json",
    health: "/health",
    verification: "/.well-known/xagent-verification.json",
    boundary: "RESEARCH_STATE_NOT_TRADE"
  }, "public, max-age=60");
}
