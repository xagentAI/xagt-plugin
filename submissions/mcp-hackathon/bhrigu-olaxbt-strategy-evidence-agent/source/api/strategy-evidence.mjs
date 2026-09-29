import { sendJson } from "../lib/http.mjs";
import { buildStrategyEvidence } from "../lib/strategy-evidence.mjs";

async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  if (typeof req.body === "string") return req.body ? JSON.parse(req.body) : null;
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 65536) throw new Error("BODY_TOO_LARGE");
  }
  return raw ? JSON.parse(raw) : null;
}

function statusFor(error) {
  if (error?.code === "UNSUPPORTED_SYMBOL") return 400;
  if (error?.code === "OLAXBT_NEXUS_API_KEY_MISSING") return 503;
  if (error?.code === "OLAXBT_UPSTREAM_AUTH_FAILED") return 502;
  if (String(error?.message || "").includes("BODY_TOO_LARGE")) return 413;
  if (error instanceof SyntaxError) return 400;
  return 502;
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "METHOD_NOT_ALLOWED", allowed: ["POST"] });
    return;
  }

  try {
    const body = await readBody(req);
    if (!body || typeof body !== "object" || !body.symbol) {
      sendJson(res, 400, { error: "INVALID_INPUT", required: { symbol: "BTC/USDT" } });
      return;
    }
    const result = await buildStrategyEvidence({ symbol: body.symbol });
    sendJson(res, 200, result);
  } catch (error) {
    sendJson(res, statusFor(error), {
      error: error?.code || (error instanceof SyntaxError ? "INVALID_JSON" : "OLAXBT_STRATEGY_EVIDENCE_UNAVAILABLE"),
      detail: String(error?.message || error),
      trading_authority: false,
      trade_execution: false
    });
  }
}
