import http from "node:http";
import { buildState } from "./lib/state.mjs";
import { healthPayload, verificationPayload } from "./lib/runtime.mjs";

const port = Number(process.env.PORT || 3000);
const json = (res, status, body) => {
  res.writeHead(status, { "content-type": "application/json", "access-control-allow-origin": "*" });
  res.end(JSON.stringify(body));
};

http.createServer(async (req, res) => {
  if (req.method !== "GET") return json(res, 405, { error: "METHOD_NOT_ALLOWED" });
  const url = new URL(req.url, `http://${req.headers.host}`);
  if (url.pathname === "/health") return json(res, 200, healthPayload());
  if (url.pathname === "/.well-known/xagent-verification.json") return json(res, 200, verificationPayload());
  if (url.pathname === "/") return json(res, 200, {
    name: "BHRIGU Bitcoin Research State API",
    endpoint: "/v1/state",
    boundary: "RESEARCH_STATE_NOT_TRADE"
  });
  if (url.pathname !== "/v1/state") return json(res, 404, { error: "NOT_FOUND" });
  if ((url.searchParams.get("symbol") || "BTCUSDT").toUpperCase() !== "BTCUSDT") {
    return json(res, 400, { error: "UNSUPPORTED_SYMBOL", supported: ["BTCUSDT"] });
  }
  try { return json(res, 200, await buildState()); }
  catch (error) { return json(res, 502, { error: "PUBLIC_MARKET_SOURCE_UNAVAILABLE", detail: String(error.message || error) }); }
}).listen(port, () => console.log(`BHRIGU research state API listening on ${port}`));
