import assert from "node:assert/strict";
import { buildStrategyEvidence, normalizeStrategySymbol } from "../lib/strategy-evidence.mjs";
import { OlaXbtNexusError } from "../lib/olaxbt-nexus.mjs";

function toolFromRequest(options) {
  return JSON.parse(options.body).name;
}

const successPayloads = {
  get_strategy_signal: {
    ok: true,
    name: "get_strategy_signal",
    strategy_id: "str_test",
    content: {
      symbol: "BTC/USDT",
      trade_intent: "SELL",
      reasoning_log: "technical factors aligned bearish",
      timestamp: 1789205458,
      confidence: 0.16865581885564507
    }
  },
  get_strategy_metrics: {
    ok: true,
    name: "get_strategy_metrics",
    strategy_id: "str_test",
    content: {
      sharpe_ratio: 1.7668,
      trading_period_days: 179,
      estimated_aum_usdt: 100000,
      profit_factor: 1.6494,
      max_drawdown: "0.31%",
      total_return_pct: 0.3837,
      win_rate_pct: 52.94,
      trade_count: 17,
      status: "NOT_QUALIFIED"
    }
  },
  get_strategy_trades: { result: { trades: [
    { pnl: 4, exit_reason: "take_profit" },
    { pnl: -1, exit_reason: "stop" },
    { pnl: 2, exit_reason: "rule" },
    { pnl: 1, exit_reason: "rule" }
  ] } },
  get_strategy_equity: { data: { equity_curve: [100, 103, 109, 114] } }
};

const successFetch = async (_url, options) => new Response(JSON.stringify(successPayloads[toolFromRequest(options)]), {
  status: 200,
  headers: { "content-type": "application/json" }
});

assert.equal(normalizeStrategySymbol("BTCUSDT"), "BTC/USDT");
assert.throws(() => normalizeStrategySymbol("ETH/USDT"), /Only BTC\/USDT/);

const evidence = await buildStrategyEvidence({
  symbol: "BTC/USDT",
  apiKey: "test-key",
  fetchImpl: successFetch,
  now: new Date("2026-09-12T07:30:00Z")
});
assert.equal(evidence.signal.direction, "SELL");
assert.equal(evidence.signal.confidence, 0.16865581885564507);
assert.equal(evidence.strategy_evidence.sharpe_ratio, 1.7668);
assert.equal(evidence.strategy_evidence.win_rate, 52.94);
assert.equal(evidence.recent_behavior.sample_size, 4);
assert.ok(Math.abs(evidence.equity_context.change_pct - 14) < 1e-9);
assert.equal(evidence.assessment, "SUPPORTED");
assert.equal(evidence.authority.new_trading_signal_created, false);
assert.equal(evidence.authority.trade_execution, false);
assert.deepEqual(Object.values(evidence.source_status).map((item) => item.ok), [true, true, true, true]);

const noDirectionPayloads = structuredClone(successPayloads);
delete noDirectionPayloads.get_strategy_signal.content.trade_intent;
noDirectionPayloads.get_strategy_signal.content.reasoning_log = "strongly bearish reasoning text must not become a direction";
const noDirectionFetch = async (_url, options) => new Response(JSON.stringify(noDirectionPayloads[toolFromRequest(options)]), { status: 200 });
const noDirection = await buildStrategyEvidence({ symbol: "BTC/USDT", apiKey: "test-key", fetchImpl: noDirectionFetch });
assert.equal(noDirection.signal.direction, null);

await assert.rejects(
  () => buildStrategyEvidence({ symbol: "BTC/USDT", fetchImpl: successFetch, apiKey: "" }),
  (error) => error instanceof OlaXbtNexusError && error.code === "OLAXBT_NEXUS_API_KEY_MISSING"
);

const authFetch = async () => new Response(JSON.stringify({ error: "unauthorized" }), {
  status: 401,
  headers: { "content-type": "application/json" }
});
await assert.rejects(
  () => buildStrategyEvidence({ symbol: "BTC/USDT", apiKey: "bad-key", fetchImpl: authFetch }),
  (error) => error instanceof OlaXbtNexusError && error.code === "OLAXBT_UPSTREAM_AUTH_FAILED"
);

const partialFetch = async (_url, options) => {
  const tool = toolFromRequest(options);
  if (tool === "get_strategy_trades") return new Response(JSON.stringify({ error: "temporary" }), { status: 503 });
  return new Response(JSON.stringify(successPayloads[tool]), { status: 200 });
};
const partial = await buildStrategyEvidence({ symbol: "BTC/USDT", apiKey: "test-key", fetchImpl: partialFetch });
assert.equal(partial.source_status.trades.ok, false);
assert.ok(partial.limitations.some((item) => item.includes("trades source unavailable")));

const malformedFetch = async (_url, options) => {
  const tool = toolFromRequest(options);
  if (tool === "get_strategy_equity") return new Response("<html>bad gateway</html>", { status: 200 });
  return new Response(JSON.stringify(successPayloads[tool]), { status: 200 });
};
const malformed = await buildStrategyEvidence({ symbol: "BTC/USDT", apiKey: "test-key", fetchImpl: malformedFetch });
assert.equal(malformed.source_status.equity.code, "OLAXBT_UPSTREAM_MALFORMED_RESPONSE");

console.log(JSON.stringify({
  schema: "bhrigu_olaxbt_strategy_evidence_tests_v0_1",
  status: "PASS",
  checks: 21
}, null, 2));
