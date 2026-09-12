import { fetchMarket, fetchProtocol } from "./live.mjs";
import { WINDOW } from "./window.mjs";
import { SCHEMA, runtimeCommit } from "./runtime.mjs";
import { temporalSummary } from "./windows.mjs";

export async function buildState({ fetchImpl = fetch, now = new Date() } = {}) {
  const [market, protocol] = await Promise.all([
    fetchMarket(fetchImpl), fetchProtocol(fetchImpl)
  ]);
  const observedAt = now.toISOString();
  const sourceAgeMs = Math.max(0, now.getTime() - market.source_close_time_ms);
  const freshness = sourceAgeMs <= 120000 ? "FRESH" : "STALE";
  const epochStart = 840000;
  const nextEpoch = 1050000;
  const height = protocol.height;
  const progress = height === null ? null : Math.max(0, Math.min(1, (height - epochStart) / (nextEpoch - epochStart)));
  const boundary = new Date(WINDOW.boundary_utc);
  const phase = now < boundary ? "PRE_BOUNDARY" : "POST_BOUNDARY";
  const baseline = WINDOW.baseline.btcusdt_last_price;
  const deltaPct = ((market.last_price_usdt - baseline) / baseline) * 100;

  return {
    schema: SCHEMA,
    commit: runtimeCommit(),
    observed_at_utc: observedAt,
    boundary: "RESEARCH_STATE_NOT_TRADE",
    market: { ...market, freshness, source_age_ms: sourceAgeMs },
    protocol_time: {
      halving_epoch: 4,
      epoch_start_height: epochStart,
      next_epoch_height: nextEpoch,
      block_subsidy_btc: 3.125,
      live_tip_height: height,
      epoch_progress_pct: progress === null ? null : Number((progress * 100).toFixed(4)),
      source: protocol.source,
      source_status: protocol.status
    },
    window: {
      ...WINDOW,
      phase,
      current_vs_baseline_pct: Number(deltaPct.toFixed(4)),
      comparison_status: phase === "PRE_BOUNDARY" ? "NOT_FINAL_BEFORE_BOUNDARY" : "REALITY_COMPARISON_OPEN"
    },
    temporal_evidence: temporalSummary(now),
    memory: {
      law: "FIELD → WINDOW → REALITY → MEMORY",
      append_only: true,
      retroactive_rewrite: "forbidden"
    },
    authority: {
      trading: false, wallet: false, payment: false, withdrawal: false,
      transfer: false, private_account_data: false, credentials_read: false
    },
    limits: {
      method: "GET",
      symbol: "BTCUSDT only",
      auth: "none",
      market_source: "public Binance Spot",
      protocol_source: "public mempool.space tip height"
    }
  };
}
