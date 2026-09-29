import { methodGate, sendJson } from "../lib/http.mjs";

export default function handler(req, res) {
  if (!methodGate(req, res)) return;
  sendJson(res, 200, {
    name: "BHRIGU Bitcoin Research State API",
    capability: "read-only Bitcoin research state",
    endpoint: "/v1/state",
    health: "/health",
    verification: "/.well-known/xagent-verification.json",
    boundary: "RESEARCH_STATE_NOT_TRADE"
  }, "public, max-age=60");
}
