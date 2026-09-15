import http from "node:http";
import { buildState } from "./lib/state.mjs";
import { healthPayload, verificationPayload } from "./lib/runtime.mjs";
import { getWindow, listWindows, temporalSummary } from "./lib/windows.mjs";
import { handleMcpRpc } from "./lib/mcp.mjs";
import { openapiPayload } from "./lib/openapi.mjs";

const port = Number(process.env.PORT || 3000);
const json = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*" });
  res.end(body === null ? "" : JSON.stringify(body));
};
const readJson = (req) => new Promise((resolve, reject) => {
  let raw = "";
  req.on("data", (chunk) => {
    raw += chunk;
    if (raw.length > 65536) reject(new Error("BODY_TOO_LARGE"));
  });
  req.on("end", () => {
    try { resolve(raw ? JSON.parse(raw) : null); } catch (error) { reject(error); }
  });
  req.on("error", reject);
});

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);

  if (url.pathname === "/mcp") {
    if (req.method !== "POST") return json(res, 405, { error: "METHOD_NOT_ALLOWED", allowed: ["POST"] });
    try {
      const result = await handleMcpRpc(await readJson(req), {
        transportMeta: {
          requireHeaders: true,
          protocolVersion: req.headers["mcp-protocol-version"] ?? null,
          method: req.headers["mcp-method"] ?? null,
          name: req.headers["mcp-name"] ?? null
        }
      });
      if (result.status === 202) return json(res, 202, null);
      return json(res, result.status, result.body);
    } catch {
      return json(res, 400, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
    }
  }

  if (req.method !== "GET") return json(res, 405, { error: "METHOD_NOT_ALLOWED" });
  if (url.pathname === "/health") return json(res, 200, healthPayload());
  if (url.pathname === "/.well-known/xagent-verification.json") return json(res, 200, verificationPayload());
  if (url.pathname === "/openapi.json") return json(res, 200, openapiPayload());
  if (url.pathname === "/v1/windows") return json(res, 200, { ...temporalSummary(), windows: listWindows() });
  if (url.pathname.startsWith("/v1/windows/")) {
    const id = decodeURIComponent(url.pathname.slice("/v1/windows/".length));
    const record = getWindow(id);
    return record ? json(res, 200, record) : json(res, 404, { error: "WINDOW_NOT_FOUND" });
  }
  if (url.pathname === "/") return json(res, 200, {
    name: "BHRIGU Bitcoin Temporal Evidence",
    endpoint: "/v1/state",
    windows: "/v1/windows",
    mcp: "/mcp",
    openapi: "/openapi.json",
    boundary: "RESEARCH_STATE_NOT_TRADE"
  });
  if (url.pathname !== "/v1/state") return json(res, 404, { error: "NOT_FOUND" });
  if ((url.searchParams.get("symbol") || "BTCUSDT").toUpperCase() !== "BTCUSDT") {
    return json(res, 400, { error: "UNSUPPORTED_SYMBOL", supported: ["BTCUSDT"] });
  }
  try { return json(res, 200, await buildState()); }
  catch (error) { return json(res, 502, { error: "PUBLIC_MARKET_SOURCE_UNAVAILABLE", detail: String(error.message || error), trading_authority: false }); }
}).listen(port, () => console.log(`BHRIGU temporal evidence API listening on ${port}`));
