// PM Brier — read-only calibration score from settled Polymarket positions.
// Productizes polymarket-toolkit computeBrierScoreFromSettledPositions.

const SERVICE_ID = 'pm_brier';
const LB_BASE = 'https://lb-api.polymarket.com';
const DATA_BASE = 'https://data-api.polymarket.com';
const FETCH_TIMEOUT_MS = 12000;
const EVM = /^0x[a-fA-F0-9]{40}$/;

const STANDARD_CAVEATS = [
  'Read-only calibration sample from Data API positions page — not full-history Brier.',
  'Settled rows use redeemable=true; win if currentValue > 0.',
  'No wallet custody, no trade execution.'
];

// 2026-07-30 — measured against live Data API, three leaderboard wallets plus one
// active BTC trader:
//   swisstony (#1 all-time profit): 200 positions, redeemable=0  → no sample at all
//   Theo4 / Fredi9999:              0 positions                  → no sample at all
//   0x63ce…(active):                3 positions, all redeemable, all currentValue=0
// /positions only carries positions that have NOT been redeemed yet. Winners get
// claimed and drop off; losers linger as zero-value dust rows. So a redeemable=true
// sample is survivorship-biased toward losses, and the bias signature is exactly
// "few rows, zero wins". Worse, cheap losing longshots produce small squared errors:
// 0x63ce scored brier=0.118 → rating "good" while win_rate was 0. A number that says
// "well calibrated" about an 0-for-3 wallet is not a soft edge case, it is wrong.
// Fix below: refuse to rate an unrepresentative sample, and report the base-rate
// reference so the score is interpretable instead of compared to a hardcoded 0.15.
const MIN_RATEABLE_SAMPLE = 10;

export async function assessPmBrierLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const raw = String(input.address ?? input.wallet ?? input.username ?? input.query ?? '').trim();
  if (!raw) throw new Error('address (0x…) or username is required');

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

  const limit = clampInt(input.limit, 50, 200, 200);
  const positions = await fetchJson(
    fetchImpl,
    `${DATA_BASE}/positions?user=${address}&limit=${limit}&sizeThreshold=0`
  ).catch(() => []);

  const list = Array.isArray(positions) ? positions : [];
  const settled = list.filter((p) => p.redeemable === true);
  const result = computeBrier(settled);

  const brier = Number.isFinite(result.brier) ? round3(result.brier) : null;
  const win_rate = result.n ? round3(result.wins / result.n) : null;

  // Brier is meaningless without a reference: predicting the sample's own base rate
  // for every market scores base_rate*(1-base_rate). Beating that is the only claim
  // this sample can support.
  const base_rate = win_rate;
  const baseline_brier =
    base_rate === null ? null : round3(base_rate * (1 - base_rate));
  const skill_vs_baseline =
    brier === null || baseline_brier === null ? null : round3(baseline_brier - brier);

  const sample_bias =
    result.n === 0
      ? 'no_settled_rows_in_positions_page'
      : result.wins === 0
        ? 'zero_wins_survivorship_suspected'
        : result.n < MIN_RATEABLE_SAMPLE
          ? 'sample_below_rateable_threshold'
          : null;

  const rating = !Number.isFinite(result.brier)
    ? 'insufficient_sample'
    : sample_bias
      ? 'not_rateable'
      : skill_vs_baseline > 0
        ? 'beats_base_rate'
        : 'no_edge_vs_base_rate';

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: { query: raw, address, resolved_via, positions_limit: limit },
    brier,
    settled_markets: result.n,
    wins: result.wins,
    win_rate,
    baseline_brier,
    skill_vs_baseline,
    sample_bias,
    rating,
    buyer_summary_zh: buildBuyerSummaryZh({
      brier,
      rating,
      n: result.n,
      wins: result.wins,
      win_rate,
      baseline_brier,
      skill_vs_baseline,
      sample_bias
    }),
    sample: settled.slice(0, 10).map((p) => ({
      title: p.title ?? p.slug ?? null,
      avg_price: toNumber(p.avgPrice),
      won: toNumber(p.currentValue) > 0,
      current_value: toNumber(p.currentValue)
    })),
    confidence_gaps: [
      'positions_page_capped',
      'redeemed_winners_absent_from_positions_page',
      ...(result.n < MIN_RATEABLE_SAMPLE ? ['small_settled_sample'] : []),
      ...(sample_bias ? [sample_bias] : [])
    ],
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Use_polymarket-brier_skill_for_full_calibration',
    source: {
      provider: 'polymarket_public_api',
      oss_lineage: 'polymarket-toolkit computeBrierScoreFromSettledPositions',
      method: 'mean((avgPrice - actual)^2) over redeemable positions'
    }
  };
}

export function buildPmBrierFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: { query: input.address ?? input.username ?? null, address: null, resolved_via: null },
    brier: null,
    settled_markets: 0,
    wins: 0,
    win_rate: null,
    rating: 'insufficient_sample',
    sample: [],
    confidence_gaps: ['live_data_unavailable'],
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Use_polymarket-brier_skill_for_full_calibration',
    source: { provider: 'static_fallback' }
  };
}

function computeBrier(settled) {
  if (!settled.length) return { brier: Number.NaN, n: 0, wins: 0 };
  let sumSq = 0;
  let wins = 0;
  for (const p of settled) {
    const f = toNumber(p.avgPrice);
    const won = toNumber(p.currentValue) > 0;
    if (won) wins += 1;
    const actual = won ? 1 : 0;
    sumSq += (f - actual) ** 2;
  }
  return { brier: sumSq / settled.length, n: settled.length, wins };
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

function round3(n) {
  return Math.round(n * 1000) / 1000;
}

function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

function buildBuyerSummaryZh({
  brier,
  rating,
  n,
  wins,
  win_rate,
  baseline_brier,
  skill_vs_baseline,
  sample_bias
}) {
  if (!Number.isFinite(brier) || !n) {
    return '样本不足：/positions 当前页没有已结算持仓，无法给出 Brier。注意该端点只保留未赎回持仓，赢单赎回后即消失，因此「查不到样本」本身不代表这个地址表现差。完整校准需走 polymarket-brier skill 的全历史口径。';
  }
  const head = `Brier=${brier}，已结算样本 ${n} 场，胜 ${wins}（胜率 ${win_rate}）；同样本基准率 Brier=${baseline_brier}，相对基准${skill_vs_baseline > 0 ? '领先' : '落后'} ${Math.abs(skill_vs_baseline)}。`;
  if (sample_bias === 'zero_wins_survivorship_suspected') {
    return `${head} **不给评级**：样本零胜，符合生存者偏差特征——/positions 只保留未赎回持仓，赢单赎回后消失、输单以零值留存，所以低 Brier 在这里可能只是「买便宜的单然后输」而非校准好。需全历史数据才能定论。`;
  }
  if (sample_bias === 'sample_below_rateable_threshold') {
    return `${head} **不给评级**：样本不足 ${MIN_RATEABLE_SAMPLE} 场，随机波动大于可解释的差异。`;
  }
  return `${head} 结论：${rating === 'beats_base_rate' ? '在该样本上优于基准率' : '在该样本上未跑赢基准率'}。这是抽样信号，不是完整历史审计（赢单赎回后不在本端点内）。`;
}
