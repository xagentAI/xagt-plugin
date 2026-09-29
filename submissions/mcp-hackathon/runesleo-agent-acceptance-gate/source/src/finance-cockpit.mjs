// Finance Cockpit — compose Crypto Market Regime + Event Price Divergence
// into one "副驾驶" card for agents. Read-only, no orders.

import {
  assessCryptoMarketRegimeLive,
  buildCryptoMarketRegimeFallback
} from './crypto-market-regime.mjs';
import {
  assessEventPriceDivergenceLive,
  buildEventPriceDivergenceFallback
} from './event-price-divergence.mjs';

const SERVICE_ID = 'finance_cockpit';

const STANDARD_CAVEATS = [
  'Composed research card only. Not investment advice; does not place or route orders.',
  'Regime score and divergence signals are independent heuristics — disagreement is informative, not an error.',
  'No wallet custody, no trade execution.'
];

export async function assessFinanceCockpitLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const focus = input.focus ?? input.asset ?? 'all';
  const limit = clampInt(input.limit, 1, 10, 5);

  const [regimeResult, divergenceResult] = await Promise.allSettled([
    assessCryptoMarketRegimeLive({ focus, asset: focus, limit }, { fetchImpl }),
    assessEventPriceDivergenceLive({ asset: focus === 'all' ? 'all' : focus, limit }, { fetchImpl })
  ]);

  const regime = regimeResult.status === 'fulfilled'
    ? regimeResult.value
    : buildCryptoMarketRegimeFallback({ focus, limit });
  const divergence = divergenceResult.status === 'fulfilled'
    ? divergenceResult.value
    : buildEventPriceDivergenceFallback({ asset: focus, limit });

  if (regimeResult.status === 'rejected' && divergenceResult.status === 'rejected') {
    throw new Error('Both regime and divergence upstream paths failed');
  }

  const action = deriveAction(regime, divergence);
  const buyer_summary_zh = buildBuyerSummaryZh(action, regime, divergence);

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: { focus, limit },
    action,
    buyer_summary_zh,
    value_loop: {
      why_pay_again: 'Regime score and divergence signals refresh with live OKX/PM data; useful on a monitor cadence.',
      stale_after_minutes: 15,
      best_used_in: 'crypto_research_or_risk_dashboard_loop',
      paid_value_tier: 'A_repeat_monitoring'
    },
    regime: {
      regime: regime.regime,
      score: regime.score,
      confidence: regime.confidence,
      summary: regime.summary,
      buyer_summary_zh: regime.buyer_summary_zh ?? null,
      oi_context: regime.oi_context ?? null,
      source_status: regime.source?.source_status ?? null
    },
    divergence: {
      summary: divergence.summary,
      buyer_summary_zh: divergence.buyer_summary_zh ?? null,
      signal_count: Array.isArray(divergence.signals) ? divergence.signals.length : 0,
      top_signals: (divergence.signals || []).slice(0, limit),
      source_status: divergence.source?.source_status ?? null
    },
    caveats: [
      ...STANDARD_CAVEATS,
      ...(regimeResult.status === 'rejected'
        ? [`Regime leg degraded: ${regimeResult.reason?.message || regimeResult.reason}`]
        : []),
      ...(divergenceResult.status === 'rejected'
        ? [`Divergence leg degraded: ${divergenceResult.reason?.message || divergenceResult.reason}`]
        : [])
    ],
    next_gate: 'Use_pm_trade_preflight_or_human_risk_limits_before_orders',
    source: {
      method: 'compose_crypto_market_regime_plus_event_price_divergence',
      prize_track_fit: '金融副驾驶'
    }
  };
}

export function buildFinanceCockpitFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: { focus: input.focus ?? input.asset ?? 'all', limit: clampInt(input.limit, 1, 10, 5) },
    action: 'hold_observe',
    buyer_summary_zh: '演示回退：实时行情不可用，默认 hold_observe。',
    regime: null,
    divergence: null,
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Use_pm_trade_preflight_or_human_risk_limits_before_orders',
    source: { method: 'static_fallback' }
  };
}

function deriveAction(regime, divergence) {
  const signals = divergence?.signals?.length || 0;
  const score = Number(regime?.score);
  const label = regime?.regime;
  if (label === 'mixed' || (signals >= 2 && Number.isFinite(score) && Math.abs(score - 50) < 8)) {
    return 'hold_observe';
  }
  if (label === 'risk_on' && score >= 65 && signals === 0) return 'risk_on_clean';
  if (label === 'risk_off' && score <= 35 && signals === 0) return 'risk_off_clean';
  if (signals >= 1) return 'divergence_review';
  return 'hold_observe';
}

function buildBuyerSummaryZh(action, regime, divergence) {
  const actionZh = {
    risk_on_clean: '偏多且无明显背离',
    risk_off_clean: '偏空且无明显背离',
    divergence_review: '存在概率/现货背离，先复核',
    hold_observe: '观望/信号混杂'
  }[action] || action;
  const r = regime?.regime ?? 'n/a';
  const s = regime?.score ?? 'n/a';
  const n = divergence?.signals?.length ?? 0;
  return `副驾驶结论：${actionZh}。Regime=${r}（${s}/100），背离信号 ${n} 条。组合卡，非下单指令。`;
}

function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}
