import { buildState } from "../lib/state.mjs";
import { methodGate, sendJson } from "../lib/http.mjs";

export default async function handler(req, res) {
  if (!methodGate(req, res)) return;
  const url = new URL(req.url || "/v1/state", "http://localhost");
  const symbol = String(url.searchParams.get("symbol") || "BTCUSDT").toUpperCase();
  if (symbol !== "BTCUSDT") {
    sendJson(res, 400, { error: "UNSUPPORTED_SYMBOL", supported: ["BTCUSDT"] });
    return;
  }
  try {
    const state = await buildState();
    sendJson(res, 200, state, "public, max-age=10, s-maxage=10");
  } catch (error) {
    sendJson(res, 502, {
      error: "PUBLIC_MARKET_SOURCE_UNAVAILABLE",
      source: "Binance Spot BTCUSDT",
      detail: String(error.message || error),
      trading_authority: false
    });
  }
}
