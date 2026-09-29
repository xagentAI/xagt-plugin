// Sports Cockpit — compose Sports Smart Money + Sports Upset into one card.
// World Cup is one league scope, not the product identity.

import { assessSportsSmartMoneyLive } from './worldcup-smart-money-live.mjs';
import {
  assessSportsUpsetAlertLive,
  buildSportsUpsetAlertFallback
} from './sports-upset-alert.mjs';
import { assessWorldCupSmartMoney } from './worldcup-smart-money.mjs';

const SERVICE_ID = 'sports_cockpit';

const STANDARD_CAVEATS = [
  'Composed sports prediction-market card only. Not betting advice; does not place or route orders.',
  'Smart-money and upset legs share the same public Polymarket scan heuristics and can be wrong or stale.',
  'No wallet custody, no trade execution.'
];

export async function assessSportsCockpitLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const limit = clampInt(input.limit, 1, 10, 5);
  const scope = {
    sport: input.sport ?? 'all',
    league: input.league ?? null,
    tag_slug: input.tag_slug ?? null,
    query: input.query ?? input.market ?? 'all',
    max_prob: input.max_prob ?? input.max_implied_probability ?? 0.35,
    limit
  };

  const [smartResult, upsetResult] = await Promise.allSettled([
    assessSportsSmartMoneyLive(scope, { fetchImpl }),
    assessSportsUpsetAlertLive(scope, { fetchImpl })
  ]);

  const smart = smartResult.status === 'fulfilled'
    ? smartResult.value
    : assessWorldCupSmartMoney(scope);
  const upset = upsetResult.status === 'fulfilled'
    ? upsetResult.value
    : buildSportsUpsetAlertFallback(scope);

  if (smartResult.status === 'rejected' && upsetResult.status === 'rejected') {
    throw new Error('Both sports smart-money and upset upstream paths failed');
  }

  const signals = smart.signals || [];
  const alerts = upset.upset_alerts || [];
  const cohort = smart.wallet_cohort || upset.wallet_cohort || [];
  const action = alerts.length
    ? 'upset_watch'
    : (signals.length ? 'follow_smart_money_review' : 'no_signal');

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: scope,
    action,
    buyer_summary_zh: buildBuyerSummaryZh(action, scope, signals, alerts, cohort),
    value_loop: {
      why_pay_again: 'Large trades and upset flow change continuously; re-scan before acting on sports PM.',
      stale_after_minutes: 10,
      best_used_in: 'sports_pm_watchlist_or_pretrade_scan',
      paid_value_tier: 'A_repeat_monitoring'
    },
    smart_money: {
      summary: smart.summary,
      signal_count: signals.length,
      signals: signals.slice(0, limit),
      wallet_cohort: (cohort || []).slice(0, 5)
    },
    upset: {
      summary: upset.summary,
      alert_count: alerts.length,
      max_prob: upset.input?.max_prob ?? scope.max_prob,
      upset_alerts: alerts.slice(0, limit)
    },
    caveats: [
      ...STANDARD_CAVEATS,
      ...(smartResult.status === 'rejected'
        ? [`Smart-money leg degraded: ${smartResult.reason?.message || smartResult.reason}`]
        : []),
      ...(upsetResult.status === 'rejected'
        ? [`Upset leg degraded: ${upsetResult.reason?.message || upsetResult.reason}`]
        : [])
    ],
    next_gate: 'Use_pm_trade_preflight_before_any_order',
    source: {
      method: 'compose_sports_smart_money_plus_sports_upset',
      discovery: smart.source?.discovery || upset.source?.discovery || null
    }
  };
}

export function buildSportsCockpitFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      sport: input.sport ?? null,
      league: input.league ?? null,
      query: input.query ?? 'all',
      limit: clampInt(input.limit, 1, 10, 5)
    },
    action: 'no_signal',
    buyer_summary_zh: '演示回退：实时体育扫描不可用。',
    smart_money: null,
    upset: null,
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Use_pm_trade_preflight_before_any_order',
    source: { method: 'static_fallback' }
  };
}

function buildBuyerSummaryZh(action, scope, signals, alerts, cohort) {
  const actionZh = {
    upset_watch: '有冷门预警，优先看低概率侧',
    follow_smart_money_review: '有聪明钱信号，先复核再跟',
    no_signal: '当前范围无明显信号'
  }[action] || action;
  const label = [scope.sport, scope.league, scope.query].filter(Boolean).join('/') || 'sports';
  const cross = (cohort || []).filter((w) => w.cross_market).length;
  return `体育副驾驶：${actionZh}（范围 ${label}）。聪明钱 ${signals.length} 条 / 冷门 ${alerts.length} 条` +
    (cross ? ` / 跨场钱包 ${cross}` : '') +
    '。非投注建议。';
}

function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}
