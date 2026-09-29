import { callOlaXbtTool, OlaXbtNexusError, resolveOlaXbtApiKey } from "./olaxbt-nexus.mjs";

const TOOL_SPECS = Object.freeze([
  ["signal", "get_strategy_signal"],
  ["metrics", "get_strategy_metrics"],
  ["trades", "get_strategy_trades"],
  ["equity", "get_strategy_equity"]
]);

function normalizeKey(key) {
  return String(key).toLowerCase().replace(/[^a-z0-9]/g, "");
}

function walkObjects(value, visit, depth = 0) {
  if (depth > 6 || value == null) return;
  if (Array.isArray(value)) {
    for (const item of value) walkObjects(item, visit, depth + 1);
    return;
  }
  if (typeof value !== "object") return;
  visit(value);
  for (const child of Object.values(value)) walkObjects(child, visit, depth + 1);
}

function findValue(root, aliases) {
  const wanted = new Set(aliases.map(normalizeKey));
  let found;
  walkObjects(root, (obj) => {
    if (found !== undefined) return;
    for (const [key, value] of Object.entries(obj)) {
      if (wanted.has(normalizeKey(key)) && value !== null && value !== undefined) {
        found = value;
        return;
      }
    }
  });
  return found;
}

function findArray(root, aliases) {
  if (Array.isArray(root)) return root;
  const value = findValue(root, aliases);
  return Array.isArray(value) ? value : null;
}

function asFiniteNumber(value) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const normalized = value.trim().replace(/,/g, "").replace(/%$/, "");
  if (!normalized) return null;
  const number = Number(normalized);
  return Number.isFinite(number) ? number : null;
}

function asString(value) {
  if (value == null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return null;
}

function percentIsPositive(value) {
  const number = asFiniteNumber(value);
  return number == null ? null : number > 0;
}

function winRateIsPositive(value) {
  const number = asFiniteNumber(value);
  if (number == null) return null;
  return number <= 1 ? number >= 0.5 : number >= 50;
}

function extractSignal(payload) {
  return {
    direction: asString(findValue(payload, ["signal", "direction", "trade_intent", "action", "side"])),
    confidence: asFiniteNumber(findValue(payload, ["confidence", "confidence_score", "score"])),
    reasoning_log: asString(findValue(payload, ["reasoning_log", "reasoning", "reason", "log"]))
  };
}

function extractMetrics(payload) {
  return {
    sharpe_ratio: asFiniteNumber(findValue(payload, ["sharpe_ratio", "sharpe"])),
    return_pct: asFiniteNumber(findValue(payload, ["return_pct", "return_percent", "total_return_pct", "total_return", "return"])),
    win_rate: asFiniteNumber(findValue(payload, ["win_rate", "win_rate_pct", "winrate"])),
    profit_factor: asFiniteNumber(findValue(payload, ["profit_factor", "profitfactor"])),
    max_drawdown_pct: asFiniteNumber(findValue(payload, ["max_drawdown_pct", "max_drawdown_percent", "max_drawdown", "drawdown"])),
    trade_count: asFiniteNumber(findValue(payload, ["trade_count", "trades_count", "num_trades", "total_trades"]))
  };
}

function extractTrades(payload) {
  const trades = findArray(payload, ["trades", "trade_list", "items", "records"]);
  if (!trades) return { observed: false, sample_size: 0, positive_count: null, negative_count: null, positive_share: null, latest_exit_reason: null };
  const recent = trades.slice(-20);
  const pnlValues = recent
    .map((trade) => asFiniteNumber(findValue(trade, ["pnl", "profit", "profit_loss", "realized_pnl", "return_pct", "return"])))
    .filter((value) => value !== null);
  const positive = pnlValues.filter((value) => value > 0).length;
  const negative = pnlValues.filter((value) => value < 0).length;
  const latest = recent.at(-1) ?? null;
  return {
    observed: true,
    sample_size: recent.length,
    positive_count: pnlValues.length ? positive : null,
    negative_count: pnlValues.length ? negative : null,
    positive_share: pnlValues.length ? positive / pnlValues.length : null,
    latest_exit_reason: latest ? asString(findValue(latest, ["exit_reason", "reason", "close_reason"])) : null
  };
}

function equityValue(point) {
  if (typeof point === "number") return Number.isFinite(point) ? point : null;
  if (typeof point === "string") return asFiniteNumber(point);
  if (point && typeof point === "object") return asFiniteNumber(findValue(point, ["equity", "value", "balance", "portfolio_value", "nav"]));
  return null;
}

function extractEquity(payload) {
  const series = findArray(payload, ["equity_curve", "equity", "points", "series", "values"]);
  if (!series || series.length < 2) return { observed: false, point_count: series?.length || 0, first: null, last: null, change_pct: null };
  const values = series.map(equityValue).filter((value) => value !== null);
  if (values.length < 2) return { observed: false, point_count: series.length, first: null, last: null, change_pct: null };
  const first = values[0];
  const last = values.at(-1);
  return {
    observed: true,
    point_count: values.length,
    first,
    last,
    change_pct: first !== 0 ? ((last - first) / Math.abs(first)) * 100 : null
  };
}

function buildAssessment({ signal, metrics, trades, equity, sourceStatus }) {
  const supports = [];
  const contradictions = [];
  const limitations = [];
  let positive = 0;
  let negative = 0;
  let observed = 0;

  const observe = (condition, supportText, contradictionText) => {
    if (condition == null) return;
    observed += 1;
    if (condition) {
      positive += 1;
      supports.push(supportText);
    } else {
      negative += 1;
      contradictions.push(contradictionText);
    }
  };

  observe(percentIsPositive(metrics.return_pct), "Historical strategy return is positive.", "Historical strategy return is non-positive.");
  observe(metrics.sharpe_ratio == null ? null : metrics.sharpe_ratio > 0, "Historical Sharpe ratio is positive.", "Historical Sharpe ratio is non-positive.");
  observe(metrics.profit_factor == null ? null : metrics.profit_factor > 1, "Historical profit factor is above 1.", "Historical profit factor is not above 1.");
  observe(winRateIsPositive(metrics.win_rate), "Historical win rate is at least 50% on the source scale.", "Historical win rate is below 50% on the source scale.");
  observe(equity.change_pct == null ? null : equity.change_pct > 0, "Observed equity curve ends above its starting point.", "Observed equity curve does not end above its starting point.");
  observe(trades.positive_share == null ? null : trades.positive_share >= 0.5, "At least half of recent trades with numeric PnL are positive.", "Fewer than half of recent trades with numeric PnL are positive.");

  if (!signal.direction) limitations.push("Current OlaXBT signal direction is unavailable.");
  if (metrics.trade_count != null && metrics.trade_count < 5) limitations.push("Historical trade count is very small; evidence is thin.");
  for (const [name, status] of Object.entries(sourceStatus)) {
    if (!status.ok) limitations.push(`${name} source unavailable: ${status.code}.`);
  }

  let assessment = "MIXED";
  if (!signal.direction || observed < 3) assessment = "INSUFFICIENT";
  else if (positive >= 3 && negative <= 1) assessment = "SUPPORTED";
  else if (negative >= 3 && positive <= 1) assessment = "WEAK";

  return {
    assessment,
    scope: "Historical strategy-evidence quality around the observed OlaXBT signal; not a new trading signal or forecast.",
    observed_dimensions: observed,
    positive_dimensions: positive,
    negative_dimensions: negative,
    supports,
    contradictions,
    limitations
  };
}

export function normalizeStrategySymbol(input) {
  const normalized = String(input || "").trim().toUpperCase().replace(/\s+/g, "");
  if (normalized === "BTCUSDT" || normalized === "BTC/USDT") return "BTC/USDT";
  throw new OlaXbtNexusError("UNSUPPORTED_SYMBOL", "Only BTC/USDT is supported in the minimum vertical slice.");
}

export async function buildStrategyEvidence({
  symbol,
  fetchImpl = fetch,
  apiKey = null,
  now = new Date()
} = {}) {
  const normalizedSymbol = normalizeStrategySymbol(symbol);
  const key = apiKey || resolveOlaXbtApiKey();

  const settled = await Promise.allSettled(TOOL_SPECS.map(([kind, tool]) => callOlaXbtTool(
    tool,
    tool === "get_strategy_signal" ? { symbol: normalizedSymbol } : {},
    { fetchImpl, apiKey: key }
  ).then((value) => ({ kind, ...value }))));

  const results = {};
  const sourceStatus = {};
  for (let i = 0; i < TOOL_SPECS.length; i += 1) {
    const [kind, tool] = TOOL_SPECS[i];
    const item = settled[i];
    if (item.status === "fulfilled") {
      results[kind] = item.value.payload;
      sourceStatus[kind] = { ok: true, tool, http_status: item.value.status };
    } else {
      const error = item.reason;
      sourceStatus[kind] = {
        ok: false,
        tool,
        code: error?.code || "OLAXBT_UPSTREAM_UNKNOWN_ERROR",
        http_status: error?.status ?? null
      };
    }
  }

  const failures = settled.filter((item) => item.status === "rejected").map((item) => item.reason);
  if (failures.length === TOOL_SPECS.length) {
    const authFailure = failures.find((error) => error?.code === "OLAXBT_UPSTREAM_AUTH_FAILED");
    if (authFailure) throw authFailure;
  }

  const signal = extractSignal(results.signal);
  const metrics = extractMetrics(results.metrics);
  const trades = extractTrades(results.trades);
  const equity = extractEquity(results.equity);
  const assessment = buildAssessment({ signal, metrics, trades, equity, sourceStatus });

  return {
    schema: "bhrigu_olaxbt_strategy_evidence_v0_1",
    symbol: normalizedSymbol,
    observed_at: now.toISOString(),
    signal,
    strategy_evidence: metrics,
    recent_behavior: trades,
    equity_context: equity,
    assessment: assessment.assessment,
    assessment_scope: assessment.scope,
    supports: assessment.supports,
    contradictions: assessment.contradictions,
    limitations: assessment.limitations,
    source_status: sourceStatus,
    authority: {
      strategy_and_signal: "OlaXBT Nexus MCP",
      evidence_assessment: "BHRIGU derived read-only heuristic",
      new_trading_signal_created: false,
      trade_execution: false,
      wallet_authority: false
    }
  };
}
