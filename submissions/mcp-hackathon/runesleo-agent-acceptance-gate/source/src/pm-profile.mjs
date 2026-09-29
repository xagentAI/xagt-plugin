// PM Profile — read-only Polymarket wallet/profile snapshot.
// Productizes public polymarket-toolkit profile surface (LB PnL + positions sample).
// No keys, no signing, no order routing.

const SERVICE_ID = 'pm_profile';
const LB_BASE = 'https://lb-api.polymarket.com';
const DATA_BASE = 'https://data-api.polymarket.com';
const FETCH_TIMEOUT_MS = 12000;
const EVM = /^0x[a-fA-F0-9]{40}$/;

const STANDARD_CAVEATS = [
  'Read-only public Polymarket snapshot. Not investment advice.',
  'Leaderboard PnL is a platform snapshot — not audit-grade fee-inclusive PnL.',
  'Positions page is capped; large wallets may be truncated.',
  'No wallet custody, no trade execution, no order routing.'
];

/**
 * @param {object} input
 * @param {string} [input.address]
 * @param {string} [input.wallet]
 * @param {string} [input.username]
 * @param {string} [input.query]
 */
export async function assessPmProfileLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const raw = String(input.address ?? input.wallet ?? input.username ?? input.query ?? '').trim();
  if (!raw) {
    throw new Error('address (0x…) or username is required');
  }

  let address = null;
  let resolved_via = null;
  if (EVM.test(raw)) {
    address = raw.toLowerCase();
    resolved_via = 'evm_address';
  } else {
    address = await resolveUsername(fetchImpl, raw);
    resolved_via = address ? 'leaderboard_username' : null;
  }

  if (!address) {
    throw new Error(`Could not resolve wallet for "${raw}" via leaderboard username search`);
  }

  const [pnlRows, positions] = await Promise.all([
    fetchJson(fetchImpl, `${LB_BASE}/profit?address=${address}&window=7d`).catch(() => []),
    fetchJson(fetchImpl, `${DATA_BASE}/positions?user=${address}&limit=50`).catch(() => [])
  ]);

  const pnl7d = Array.isArray(pnlRows) && pnlRows[0]
    ? {
        amount: toNumber(pnlRows[0].amount),
        name: pnlRows[0].name ?? null,
        pseudonym: pnlRows[0].pseudonym ?? null,
        proxy_wallet: pnlRows[0].proxyWallet ?? address
      }
    : null;

  const posList = (Array.isArray(positions) ? positions : []).map((p) => ({
    title: p.title ?? p.slug ?? null,
    outcome: p.outcome ?? null,
    size: toNumber(p.size),
    avg_price: toNumber(p.avgPrice),
    cash_pnl: toNumber(p.cashPnl),
    cur_price: toNumber(p.curPrice),
    condition_id: p.conditionId ?? null
  }));

  const openCount = posList.filter((p) => Math.abs(p.size) > 0).length;
  const approxPosPnl = posList.reduce((sum, p) => sum + (p.cash_pnl || 0), 0);

  const displayName = pnl7d?.name ?? pnl7d?.pseudonym ?? null;
  const pnl7dAmt = pnl7d?.amount ?? null;
  const approxPnl = Math.round(approxPosPnl * 100) / 100;

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      query: raw,
      address,
      resolved_via
    },
    profile: {
      address,
      display_name: displayName,
      pnl_7d_usdt: pnl7dAmt,
      open_positions_sampled: openCount,
      approx_positions_cash_pnl: approxPnl,
      positions_sample: posList.slice(0, 20)
    },
    buyer_summary_zh: buildBuyerSummaryZh({ displayName, address, pnl7dAmt, openCount, approxPnl }),
    confidence_gaps: [
      ...(pnl7d ? [] : ['not_on_7d_leaderboard']),
      'positions_page_capped',
      'not_fee_inclusive_audit_pnl'
    ],
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Use_polymarket-toolkit_pnl_skill_for_audit_grade',
    source: {
      provider: 'polymarket_public_api',
      oss_lineage: 'polymarket-toolkit pm profile (read-only public APIs)',
      windows: { pnl: '7d', positions_limit: 50 }
    }
  };
}

export function buildPmProfileFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: { query: input.address ?? input.username ?? null, address: null, resolved_via: null },
    profile: {
      address: null,
      display_name: null,
      pnl_7d_usdt: null,
      open_positions_sampled: 0,
      approx_positions_cash_pnl: 0,
      positions_sample: []
    },
    confidence_gaps: ['live_data_unavailable'],
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Use_polymarket-toolkit_pnl_skill_for_audit_grade',
    source: { provider: 'static_fallback' }
  };
}

async function resolveUsername(fetchImpl, username) {
  const needle = username.trim().toLowerCase();
  for (let page = 0; page < 3; page++) {
    const rows = await fetchJson(
      fetchImpl,
      `${LB_BASE}/profit?window=all&limit=500&offset=${page * 500}`
    ).catch(() => []);
    if (!Array.isArray(rows) || !rows.length) break;
    for (const row of rows) {
      const n = String(row.name ?? '').toLowerCase();
      const p = String(row.pseudonym ?? '').toLowerCase();
      if (n === needle || p === needle) return String(row.proxyWallet ?? '').toLowerCase() || null;
    }
    if (rows.length < 500) break;
  }
  return null;
}

async function fetchJson(fetchImpl, url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, {
      signal: controller.signal,
      headers: { accept: 'application/json' }
    });
    if (!response.ok) throw new Error(`Upstream ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function buildBuyerSummaryZh({ displayName, address, pnl7dAmt, openCount, approxPnl }) {
  const who = displayName || shorten(address);
  const pnlBit = pnl7dAmt == null
    ? '7日榜无记录'
    : `7日榜 PnL ${pnl7dAmt >= 0 ? '+' : ''}${pnl7dAmt} USDT`;
  return `${who}：${pnlBit}；抽样持仓 ${openCount} 个，持仓现金盈亏约 ${approxPnl} USDT。只读画像，非下单建议。`;
}

function shorten(address) {
  const value = String(address ?? '');
  if (!value.startsWith('0x') || value.length < 12) return value || '钱包';
  return `${value.slice(0, 6)}…${value.slice(-4)}`;
}
