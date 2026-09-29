const SERVICE_ID = 'world_cup_smart_money_radar';

const MOCK_MARKETS = [
  {
    market_id: 'world-cup-2026-winner',
    title: '2026 World Cup Winner',
    updated_at: '2026-07-04T00:00:00Z',
    signals: [
      {
        address_label: 'wc-alpha-017',
        side: 'Argentina YES',
        action: 'increased_position',
        notional_usdt: 1840,
        seven_day_pnl_usdt: 612,
        confidence: 0.78,
        rationale: 'Profitable wallet added exposure while public odds softened.'
      },
      {
        address_label: 'wc-alpha-042',
        side: 'Brazil YES',
        action: 'reduced_position',
        notional_usdt: 960,
        seven_day_pnl_usdt: 231,
        confidence: 0.64,
        rationale: 'Top wallet trimmed into price strength after two prior profitable entries.'
      }
    ]
  },
  {
    market_id: 'world-cup-2026-group-stage',
    title: '2026 World Cup Group Stage',
    updated_at: '2026-07-04T00:00:00Z',
    signals: [
      {
        address_label: 'wc-alpha-009',
        side: 'USA reaches round of 16',
        action: 'contrarian_accumulation',
        notional_usdt: 720,
        seven_day_pnl_usdt: 188,
        confidence: 0.59,
        rationale: 'Wallet with positive World Cup history accumulated against consensus drift.'
      }
    ]
  }
];

export function assessWorldCupSmartMoney(input = {}) {
  const marketHint = normalizeText(input.market ?? input.market_id ?? input.query ?? 'all');
  const limit = clampInteger(input.limit, 1, 10, 5);

  const matchedMarkets = MOCK_MARKETS
    .filter((market) => marketHint === 'all' || normalizeText(`${market.market_id} ${market.title}`).includes(marketHint))
    .slice(0, limit);

  const markets = matchedMarkets.length ? matchedMarkets : MOCK_MARKETS.slice(0, limit);
  const signals = markets.flatMap((market) => market.signals.map((signal) => ({
    market_id: market.market_id,
    market_title: market.title,
    market_updated_at: market.updated_at,
    ...signal
  })));

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      market: input.market ?? input.market_id ?? input.query ?? 'all',
      limit
    },
    summary: buildSummary(signals),
    signals,
    caveats: [
      'Demo data only. Production service must use fresh Polymarket-derived data before listing.',
      'Data and analytics only. Not investment advice, not betting advice, and not a guarantee of future returns.',
      'No wallet custody, no user funds, no trade execution, no order routing.'
    ],
    next_gate: 'production_data_feed_and_OKX_ASP_listing_require_Leo_approval'
  };
}

function buildSummary(signals) {
  if (!signals.length) {
    return 'No smart-money movement found for the requested market.';
  }

  const top = signals
    .slice()
    .sort((a, b) => b.confidence - a.confidence)[0];

  return `${signals.length} smart-money movements found. Top signal: ${top.action} on ${top.side} in ${top.market_title}.`;
}

function normalizeText(value) {
  return String(value ?? '').trim().toLowerCase();
}

function clampInteger(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}
