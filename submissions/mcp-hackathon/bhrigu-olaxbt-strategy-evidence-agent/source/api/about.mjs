import { methodGate, sendJson } from "../lib/http.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  sendJson(res, 200, {
    name: "BHRIGU Strategy Evidence Agent",
    capability: "Can an agent trust the evidence context behind this OlaXBT strategy signal right now?",
    endpoint: "/v1/strategy-evidence",
    temporal_state: "/v1/state",
    windows: "/v1/windows",
    mcp: "/mcp",
    openapi: "/openapi.json",
    health: "/health",
    verification: "/.well-known/xagent-verification.json",
    boundary: "RESEARCH_STATE_NOT_TRADE"
  }, "public, max-age=60");
}
