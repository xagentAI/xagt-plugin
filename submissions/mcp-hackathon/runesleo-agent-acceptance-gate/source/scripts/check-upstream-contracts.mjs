#!/usr/bin/env node
/**
 * Upstream contract smoke check.
 *
 * Why this exists: on 2026-07-30 an audit of the listed services found that only 3 of
 * 38 modules carried any note about the upstream response shape they depend on. Every
 * other service reads fields like `redeemable`, `oneDayPriceChange` or `outcomePrices`
 * on faith. When an upstream renames or drops one of those, nothing throws — the field
 * reads as undefined, flows through a `?? 0` or a comparison that silently goes false,
 * and the service keeps answering with a confident but wrong verdict. Two of the bugs
 * fixed that day were exactly this failure mode wearing different clothes.
 *
 * So this is not a unit test. It is a live probe that asks each upstream for a real
 * response and asserts that the fields the code actually reads are still there. It is
 * deliberately kept out of `npm test`, which must stay offline and deterministic; run
 * it on demand, before a release, or when a service starts returning something odd.
 *
 *   node scripts/check-upstream-contracts.mjs           # all sources
 *   node scripts/check-upstream-contracts.mjs --json    # machine-readable
 *   node scripts/check-upstream-contracts.mjs --only polymarket
 *
 * Exit code is 1 if any required field is missing, so it can gate a release.
 * A network failure is reported as `unreachable`, not as a contract break — those are
 * different problems and conflating them would make the check untrustworthy.
 */

const TIMEOUT_MS = 20000;

/** Fields each source must still provide, taken from what src/*.mjs actually reads. */
const CONTRACTS = [
  {
    id: 'gamma_markets',
    label: 'Polymarket Gamma /markets',
    url: 'https://gamma-api.polymarket.com/markets?closed=false&active=true&limit=3&order=volume24hr&ascending=false',
    consumers: ['worldcup-smart-money-live', 'crypto-market-regime', 'event-price-divergence'],
    pick: (body) => (Array.isArray(body) ? body[0] : null),
    required: ['conditionId', 'question', 'slug', 'outcomes', 'outcomePrices', 'volume24hr', 'active', 'closed'],
    optional: ['enableOrderBook', 'oneDayPriceChange', 'liquidity', 'bestBid', 'bestAsk', 'endDate']
  },
  {
    id: 'gamma_events',
    label: 'Polymarket Gamma /events',
    url: 'https://gamma-api.polymarket.com/events?closed=false&active=true&limit=3&order=volume24hr&ascending=false',
    consumers: ['worldcup-smart-money-live', 'pm-event-readout'],
    pick: (body) => (Array.isArray(body) ? body[0] : null),
    required: ['slug', 'markets'],
    optional: ['closed', 'title', 'id']
  },
  {
    id: 'gamma_public_search',
    label: 'Polymarket Gamma /public-search',
    url: 'https://gamma-api.polymarket.com/public-search?q=bitcoin&events_status=active&limit_per_type=3',
    consumers: ['crypto-market-regime', 'event-price-divergence', 'worldcup-smart-money-live'],
    pick: (body) => (Array.isArray(body?.events) ? body.events[0] : null),
    required: ['markets'],
    optional: ['closed', 'slug', 'title']
  },
  {
    id: 'data_api_positions',
    label: 'Polymarket Data API /positions',
    // A wallet with settled rows, so `redeemable` is actually exercised. Public data.
    url: 'https://data-api.polymarket.com/positions?user=0x63ce342161250d705dc0b16df89036c8e5f9ba9a&limit=5&sizeThreshold=0',
    consumers: ['pm-brier', 'pm-profile', 'pm-pnl-audit', 'pm-wallet-report'],
    pick: (body) => (Array.isArray(body) ? body[0] : null),
    // redeemable drives the whole pm-brier sample; losing it silently would make every
    // wallet look like it has no settled history.
    required: ['redeemable', 'avgPrice', 'curPrice', 'currentValue', 'size', 'conditionId'],
    optional: ['title', 'slug', 'outcome', 'cashPnl', 'realizedPnl']
  },
  {
    id: 'lb_api_profit',
    label: 'Polymarket Leaderboard /profit',
    url: 'https://lb-api.polymarket.com/profit?window=7d&limit=3',
    consumers: ['pm-brier', 'pm-profile', 'worldcup-smart-money-live'],
    pick: (body) => (Array.isArray(body) ? body[0] : null),
    required: ['proxyWallet', 'amount'],
    optional: ['name', 'pseudonym']
  },
  {
    id: 'okx_ticker',
    label: 'OKX /market/ticker',
    url: 'https://www.okx.com/api/v5/market/ticker?instId=BTC-USDT',
    consumers: ['crypto-market-regime'],
    pick: (body) => (body?.code === '0' ? body?.data?.[0] : null),
    required: ['last', 'open24h'],
    optional: ['instId', 'vol24h']
  },
  {
    id: 'okx_funding',
    label: 'OKX /public/funding-rate',
    url: 'https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP',
    consumers: ['crypto-market-regime'],
    pick: (body) => (body?.code === '0' ? body?.data?.[0] : null),
    required: ['fundingRate'],
    optional: ['premium', 'nextFundingRate']
  },
  {
    id: 'okx_open_interest',
    label: 'OKX /public/open-interest',
    // Noted in crypto-market-regime: /api/v5/market/open-interest does NOT exist (404).
    url: 'https://www.okx.com/api/v5/public/open-interest?instId=BTC-USDT-SWAP',
    consumers: ['crypto-market-regime'],
    pick: (body) => (body?.code === '0' ? body?.data?.[0] : null),
    required: ['oiUsd'],
    optional: ['oi', 'instId']
  }
];

const args = process.argv.slice(2);
const asJson = args.includes('--json');
const onlyIdx = args.indexOf('--only');
const only = onlyIdx >= 0 ? args[onlyIdx + 1] : null;

async function fetchJson(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const res = await fetch(url, { signal: controller.signal, headers: { accept: 'application/json' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function checkOne(contract) {
  const row = {
    id: contract.id,
    label: contract.label,
    consumers: contract.consumers,
    status: 'ok',
    missing_required: [],
    missing_optional: [],
    note: null
  };
  let body;
  try {
    body = await fetchJson(contract.url);
  } catch (err) {
    row.status = 'unreachable';
    row.note = err.message;
    return row;
  }

  const sample = contract.pick(body);
  if (!sample || typeof sample !== 'object') {
    // An empty list is not a contract break — the query may simply match nothing now.
    row.status = 'no_sample';
    row.note = 'upstream reachable but returned no row to inspect';
    return row;
  }

  row.missing_required = contract.required.filter((f) => !(f in sample));
  row.missing_optional = (contract.optional || []).filter((f) => !(f in sample));
  if (row.missing_required.length) row.status = 'contract_break';
  else if (row.missing_optional.length) row.status = 'optional_drift';
  return row;
}

const targets = only
  ? CONTRACTS.filter((c) => c.id.includes(only) || c.label.toLowerCase().includes(only.toLowerCase()))
  : CONTRACTS;

if (!targets.length) {
  console.error(`no contract matches --only ${only}`);
  process.exit(2);
}

const results = [];
for (const contract of targets) {
  results.push(await checkOne(contract));
}

const broken = results.filter((r) => r.status === 'contract_break');
const drifted = results.filter((r) => r.status === 'optional_drift');
const unreachable = results.filter((r) => r.status === 'unreachable' || r.status === 'no_sample');

if (asJson) {
  console.log(JSON.stringify({
    checked_at: new Date().toISOString(),
    results,
    summary: {
      ok: results.filter((r) => r.status === 'ok').length,
      contract_break: broken.length,
      optional_drift: drifted.length,
      unreachable: unreachable.length
    }
  }, null, 2));
} else {
  for (const r of results) {
    const mark = { ok: 'PASS', optional_drift: 'DRIFT', no_sample: 'SKIP', unreachable: 'SKIP', contract_break: 'FAIL' }[r.status];
    console.log(`${mark.padEnd(5)} ${r.label}`);
    if (r.missing_required.length) {
      console.log(`      missing required: ${r.missing_required.join(', ')}`);
      console.log(`      consumers at risk: ${r.consumers.join(', ')}`);
    }
    if (r.missing_optional.length) {
      console.log(`      missing optional: ${r.missing_optional.join(', ')}`);
    }
    if (r.note) console.log(`      ${r.note}`);
  }
  console.log(
    `[upstream-contracts] ok=${results.length - broken.length - drifted.length - unreachable.length} ` +
    `drift=${drifted.length} break=${broken.length} skipped=${unreachable.length}`
  );
}

// Only a missing REQUIRED field fails the run. Unreachable upstreams are a network
// problem, not a contract change, and must not be able to mask or mimic one.
process.exit(broken.length ? 1 : 0);
