const SERVICES = {
  polymarket_smart_money_radar: {
    path: '/polymarket-smart-money-radar',
    title: 'Polymarket Smart Money Radar',
    category: 'finance',
    fee_usdt: '1',
    description: 'Tracks profitable Polymarket wallets across markets and highlights position changes.',
    sampleSignals: [
      {
        market_id: 'fed-rate-september-2026',
        market_title: 'Fed rate decision by September 2026',
        address_label: 'pm-alpha-104',
        side: 'No rate cut',
        action: 'increased_position',
        notional_usdt: 2360,
        seven_day_pnl_usdt: 804,
        confidence: 0.74,
        rationale: 'Profitable macro wallet added exposure while public probability stayed flat.'
      },
      {
        market_id: 'crypto-etf-approval-2026',
        market_title: 'Crypto ETF approval in 2026',
        address_label: 'pm-alpha-033',
        side: 'Yes',
        action: 'new_position',
        notional_usdt: 1180,
        seven_day_pnl_usdt: 289,
        confidence: 0.62,
        rationale: 'High win-rate wallet opened a fresh position after market depth improved.'
      }
    ]
  },
  event_probability_crypto_divergence: {
    path: '/event-probability-crypto-divergence',
    title: 'Event Probability Crypto Divergence',
    category: 'finance',
    fee_usdt: '1',
    description: 'Compares prediction-market event probability with crypto price and funding moves.',
    sampleSignals: [
      {
        event: 'Crypto ETF approval in 2026',
        probability_change_24h: 4.2,
        linked_asset: 'BTC',
        spot_change_24h: -1.1,
        funding_bias: 'neutral_to_short',
        divergence: 'event_probability_up_price_down',
        confidence: 0.67,
        rationale: 'Prediction-market probability rose while spot and funding did not confirm the move.'
      },
      {
        event: 'Major exchange enforcement action',
        probability_change_24h: 3.5,
        linked_asset: 'ETH',
        spot_change_24h: 0.4,
        funding_bias: 'long_crowded',
        divergence: 'event_risk_up_leverage_still_long',
        confidence: 0.61,
        rationale: 'Event risk increased while perp positioning remained crowded long.'
      }
    ]
  },
  crypto_market_pulse_report: {
    path: '/crypto-market-pulse-report',
    title: 'Crypto Market Pulse Report',
    category: 'finance',
    fee_usdt: '1',
    description: 'Returns a compact agent-readable crypto market pulse with flows, anomalies, and watch items.',
    sampleSignals: [
      {
        segment: 'majors',
        status: 'mixed',
        flow_bias: 'btc_outperforming_eth',
        anomaly: 'stablecoin inflow without broad risk-on confirmation',
        confidence: 0.58,
        rationale: 'Liquidity improved but breadth remains weak across majors.'
      },
      {
        segment: 'perps',
        status: 'fragile',
        flow_bias: 'funding_reheating',
        anomaly: 'long leverage rebuilding after shallow spot bounce',
        confidence: 0.63,
        rationale: 'Funding reset is incomplete, so reversal risk remains elevated.'
      }
    ]
  }
};

export function listOkxAiDataServices() {
  return Object.entries(SERVICES).map(([service_id, service]) => ({
    service_id,
    path: service.path,
    title: service.title,
    category: service.category,
    fee_usdt: service.fee_usdt,
    description: service.description,
    mode: 'public_safe_demo'
  }));
}

export function getOkxAiDataServiceByPath(pathname) {
  return Object.entries(SERVICES)
    .map(([service_id, service]) => ({ service_id, ...service }))
    .find((service) => service.path === pathname);
}

export function assessOkxAiDataService(service, input = {}) {
  const query = input.market ?? input.event ?? input.asset ?? input.query ?? 'all';
  const limit = clampInteger(input.limit, 1, 10, 5);
  const signals = service.sampleSignals.slice(0, limit);

  return {
    schema_version: '0.1',
    service_id: service.service_id,
    service_name: service.title,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: {
      query,
      limit
    },
    summary: buildSummary(service, signals),
    signals,
    caveats: [
      'Demo data only. Production service must use fresh data before listing.',
      'Data and analytics only. Not investment advice, not betting advice, and not a guarantee of future returns.',
      'No wallet custody, no user funds, no trade execution, no order routing.'
    ],
    next_gate: 'production_data_feed_and_OKX_ASP_listing_require_Leo_approval'
  };
}

function buildSummary(service, signals) {
  if (!signals.length) return `${service.title}: no signal found for the requested query.`;
  return `${service.title}: ${signals.length} demo signals generated for agent research workflows.`;
}

function clampInteger(value, min, max, fallback) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(min, Math.min(max, parsed));
}
