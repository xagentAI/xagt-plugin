import assert from "node:assert/strict";
import { handleMcpRpc, MCP_TOOLS } from "../lib/mcp.mjs";

const payloads = {
  get_strategy_signal: { ok: true, name: "get_strategy_signal", strategy_id: "str_test", content: { symbol: "BTC/USDT", trade_intent: "SELL", confidence: 0.16865581885564507, reasoning_log: "observed upstream shape" } },
  get_strategy_metrics: { ok: true, name: "get_strategy_metrics", strategy_id: "str_test", content: { sharpe_ratio: 1.7668, profit_factor: 1.6494, max_drawdown: "0.31%", total_return_pct: 0.3837, win_rate_pct: 52.94, trade_count: 17 } },
  get_strategy_trades: { result: { trades: [{ pnl: 1 }, { pnl: -1 }, { pnl: 2 }] } },
  get_strategy_equity: { data: { equity_curve: [100, 101, 102] } }
};
const fakeFetch = async (_url, options) => {
  const tool = JSON.parse(options.body).name;
  return new Response(JSON.stringify(payloads[tool]), { status: 200, headers: { "content-type": "application/json" } });
};

process.env.OLAXBT_NEXUS_API_KEY = "test-key";

const names = MCP_TOOLS.map((tool) => tool.name);
assert.equal(names.filter((name) => name === "bhrigu_get_olaxbt_strategy_evidence").length, 1);
const call = await handleMcpRpc({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "bhrigu_get_olaxbt_strategy_evidence", arguments: { symbol: "BTC/USDT" } } }, { fetchImpl: fakeFetch, now: new Date("2026-09-12T17:39:17Z") });
assert.equal(call.status, 200);
assert.equal(call.body.result.isError, false);
const out = call.body.result.structuredContent;
assert.equal(out.signal.direction, "SELL");
assert.equal(out.strategy_evidence.win_rate, 52.94);
assert.deepEqual(Object.values(out.source_status).map((item) => item.ok), [true, true, true, true]);
assert.equal(out.authority.trade_execution, false);
assert.equal(out.authority.new_trading_signal_created, false);
assert.equal(out.authority.wallet_authority, false);
const bad = await handleMcpRpc({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "bhrigu_get_olaxbt_strategy_evidence", arguments: { symbol: "ETH/USDT" } } }, { fetchImpl: fakeFetch });
assert.equal(bad.body.result.isError, true);
assert.equal(bad.body.result.structuredContent.error.code, "UNSUPPORTED_SYMBOL");
delete process.env.OLAXBT_NEXUS_API_KEY;
console.log(JSON.stringify({ schema: "bhrigu_olaxbt_mcp_tests_v0_1", status: "PASS", checks: 11 }));
