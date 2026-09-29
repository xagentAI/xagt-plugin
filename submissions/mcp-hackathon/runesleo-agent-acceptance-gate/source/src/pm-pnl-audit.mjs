// PM PnL Audit — quick trust gate + Worker-safe full cashflow replay.
// Ports polymarket-toolkit / polymarket-pnl fee-inclusive cashflow method.
// Read-only public APIs only. No wallet custody, signing, or orders.

const SERVICE_ID = 'pm_pnl_audit';
const LB_BASE = 'https://lb-api.polymarket.com';
const DATA_BASE = 'https://data-api.polymarket.com';
const FETCH_TIMEOUT_MS = 12000;
const EVM = /^0x[a-fA-F0-9]{40}$/;
const AUDIT_PASS_DELTA_USD = 10;
const PAGE_LIMIT = 500;
const ACTIVITY_OFFSET_CAP = 9500;
const POSITIONS_OFFSET_CAP = 9500;
/** Wall-clock budget for full pagination inside Worker. */
const FULL_BUDGET_MS = 9000;
const FULL_MAX_PAGES_PER_TYPE = 24;

const ACTIVITY_TYPES_FULL = [
  'TRADE',
  'REDEEM',
  'MERGE',
  'SPLIT',
  'MAKER_REBATE',
  'REWARD',
  'REFERRAL_REWARD',
  'CONVERSION'
];

const STANDARD_CAVEATS = [
  'Quick mode compares LB all-time profit with position-level cashPnL and activity first-page hints.',
  'Full mode paginates Data API /activity cashflows under a Worker time budget; pagination_incomplete means audit is not complete.',
  'Position cashPnL is approximate and can diverge from fee-inclusive wallet truth due to fees, rebates, redemptions, merges/splits, and rounding.',
  'Read-only public APIs only: no wallet custody, no signing, no order routing.'
];

/**
 * @param {object} input
 * @param {string} [input.address]
 * @param {string} [input.wallet]
 * @param {string} [input.username]
 * @param {string} [input.query]
 * @param {'quick'|'full'} [input.mode='quick']
 * @param {number} [input.positions_limit=100]
 */
export async function assessPmPnlAuditLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const raw = String(input.address ?? input.wallet ?? input.username ?? input.query ?? '').trim();
  if (!raw) throw new Error('pm-pnl-audit requires address or username.');

  const requestedMode = normalizeMode(input.mode);
  const resolved = await resolveAddress(fetchImpl, raw);
  if (!resolved.address) {
    throw new Error(
      `Could not resolve wallet for "${raw}" via leaderboard username search `
      + `(scanned ~top LB pages only). Pass a 0x proxy address for certainty.`
    );
  }

  const limit = clampInt(input.positions_limit ?? input.limit, 20, 500, 100);
  const deadline = Date.now() + (options.fullBudgetMs ?? FULL_BUDGET_MS);

  const [lbRows, positionsQuick] = await Promise.all([
    fetchJson(fetchImpl, `${LB_BASE}/profit?address=${resolved.address}&window=all`).catch(() => []),
    fetchJson(fetchImpl, `${DATA_BASE}/positions?user=${resolved.address}&limit=${limit}&sizeThreshold=0`).catch(() => [])
  ]);

  const leaderboard_profit = summarizeLeaderboard(lbRows, resolved.address);
  const positions_cash_pnl = summarizePositions(positionsQuick, limit);

  let activity_hint = null;
  let cashflow_replay = null;

  if (requestedMode === 'full') {
    cashflow_replay = await runFullCashflowReplay(fetchImpl, resolved.address, {
      deadline,
      maxPagesPerType: options.fullMaxPagesPerType ?? FULL_MAX_PAGES_PER_TYPE
    });
    activity_hint = {
      trade_rows: cashflow_replay.counts?.trade_count ?? 0,
      pagination: cashflow_replay.pagination_incomplete ? 'incomplete_or_budget_capped' : 'paged',
      caveat: cashflow_replay.complete
        ? 'Full cashflow replay finished within Worker budget.'
        : 'Full replay marked incomplete — do not treat as audit-grade truth.'
    };
  } else {
    const [tradePage, rebatePage] = await Promise.all([
      fetchJson(fetchImpl, `${DATA_BASE}/activity?user=${resolved.address}&type=TRADE&limit=500`).catch(() => []),
      fetchJson(fetchImpl, `${DATA_BASE}/activity?user=${resolved.address}&type=MAKER_REBATE&limit=200`).catch(() => [])
    ]);
    activity_hint = {
      trade_rows_first_page: Array.isArray(tradePage) ? tradePage.length : 0,
      maker_rebate_rows_first_page: Array.isArray(rebatePage) ? rebatePage.length : 0,
      pagination: 'first_page_only',
      caveat: 'Quick mode does not page through full activity history.'
    };
  }

  const divergence = requestedMode === 'full' && cashflow_replay
    ? computeReplayDivergence(leaderboard_profit, cashflow_replay)
    : computeDivergence(leaderboard_profit, positions_cash_pnl);

  const action = chooseAction(divergence, {
    positions_truncated: positions_cash_pnl.positions_truncated,
    requestedMode,
    replayComplete: cashflow_replay?.complete === true
  });

  const generated_at = new Date().toISOString();
  const stale_after_minutes = requestedMode === 'full' ? 30 : 15;
  const stale_at = new Date(Date.parse(generated_at) + stale_after_minutes * 60_000).toISOString();
  const confidence_gaps = [
    ...(leaderboard_profit.amount_usd === null ? ['leaderboard_profit_missing'] : []),
    ...(positions_cash_pnl.positions_sampled === 0 ? ['positions_cash_pnl_missing'] : []),
    ...(positions_cash_pnl.positions_truncated ? ['positions_page_may_be_truncated'] : []),
    ...(requestedMode === 'quick'
      ? ['cashflow_replay_not_run_in_quick_mode', 'activity_first_page_only']
      : []),
    ...(cashflow_replay && !cashflow_replay.complete
      ? ['cashflow_replay_incomplete', ...(cashflow_replay.pagination_incomplete_types || []).map((t) => `pagination_${t}`)]
      : [])
  ];

  return {
    schema_version: '0.2',
    service_id: SERVICE_ID,
    mode: requestedMode === 'full' ? 'live_full' : 'live_quick',
    generated_at,
    input: {
      query: raw,
      address: resolved.address,
      resolved_via: resolved.resolved_via,
      mode: requestedMode,
      positions_limit: limit
    },
    layers: {
      leaderboard_profit,
      positions_cash_pnl,
      cashflow_replay
    },
    leaderboard_profit,
    positions_cash_pnl,
    activity_hint,
    cashflow_replay,
    divergence_verdict: divergence.verdict,
    divergence,
    action,
    buyer_summary_zh: buildBuyerSummaryZh({
      resolved, leaderboard_profit, positions_cash_pnl, divergence, action, cashflow_replay, requestedMode
    }),
    buyer_summary_en: buildBuyerSummaryEn({
      resolved, leaderboard_profit, positions_cash_pnl, divergence, action, cashflow_replay, requestedMode
    }),
    value_loop: {
      why_pay_again: 'Wallet PnL, open positions and rebates move; re-run before copying a trader or trusting a PnL claim.',
      stale_after_minutes,
      stale_at,
      best_used_in: 'copy_trading_due_diligence_or_claim_verification',
      not_a_subscription_to: 'live_wallet_alerts',
      paid_value_tier: 'A_tier_audit',
      fulfillment: requestedMode === 'full'
        ? (cashflow_replay?.complete ? 'full_cashflow_replay_on_demand' : 'full_cashflow_replay_incomplete_honest')
        : 'quick_audit_on_demand',
      operator_always_online: false,
      llm_api_key_required: false
    },
    confidence_gaps,
    caveats: [
      ...STANDARD_CAVEATS,
      ...(requestedMode === 'full' && cashflow_replay && !cashflow_replay.complete
        ? ['Full replay incomplete under Worker budget or API pagination boundary — verify manually or re-run offline polymarket-pnl.']
        : [])
    ],
    next_gate: requestedMode === 'full'
      ? (cashflow_replay?.complete
        ? 'If abs delta vs LB > $10, distrust headline claims for copy-trading.'
        : 'Re-run full offline polymarket-pnl or shrink wallet history before relying on audit-grade PnL.')
      : 'If divergence matters, call mode=full for cashflow replay.',
    source: {
      provider: 'polymarket_public_api',
      oss_lineage: 'polymarket-toolkit fee-inclusive-pnl.md + pm pnl-check + polymarket-pnl skill',
      layers: requestedMode === 'full'
        ? ['lb-api /profit window=all', 'data-api /positions', 'data-api /activity cashflow replay']
        : ['lb-api /profit window=all', 'data-api /positions cashPnl', 'data-api /activity first page hints'],
      audit_threshold_usd: AUDIT_PASS_DELTA_USD,
      activity_types_full: ACTIVITY_TYPES_FULL
    }
  };
}

export function buildPmPnlAuditFallback(input = {}) {
  const generated_at = new Date().toISOString();
  return {
    schema_version: '0.2',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at,
    input: {
      query: input.address ?? input.wallet ?? input.username ?? input.query ?? null,
      address: null,
      resolved_via: null,
      mode: normalizeMode(input.mode)
    },
    layers: {
      leaderboard_profit: { amount_usd: null, source: 'lb-api /profit window=all', row_found: false },
      positions_cash_pnl: { total_cash_pnl_usd: null, positions_sampled: 0, positions_truncated: false },
      cashflow_replay: null
    },
    divergence_verdict: 'unknown',
    action: 'verify_manually',
    buyer_summary_zh: 'PnL 审计回退：实时公开 API 不可用，无法判断；请手动核对。',
    buyer_summary_en: 'PnL audit fallback: live public APIs unavailable; verify manually.',
    confidence_gaps: ['live_data_unavailable'],
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Retry live quick or full audit.',
    source: { provider: 'static_fallback' }
  };
}

async function runFullCashflowReplay(fetchImpl, address, { deadline, maxPagesPerType }) {
  const incompleteTypes = [];
  const budgetHitTypes = [];
  const counts = {
    buy_count: 0,
    sell_count: 0,
    trade_count: 0,
    redeem_count: 0,
    merge_count: 0,
    split_count: 0,
    rebate_count: 0,
    reward_count: 0,
    referral_count: 0,
    conversion_count: 0
  };

  let total_buy = 0;
  let total_sell = 0;
  let total_redeem = 0;
  let total_merge = 0;
  let total_split = 0;
  let total_rebate = 0;
  let total_reward = 0;
  let total_referral = 0;
  let total_conversion = 0;
  let pages_fetched = 0;

  for (const activityType of ACTIVITY_TYPES_FULL) {
    if (Date.now() >= deadline) {
      budgetHitTypes.push(activityType);
      incompleteTypes.push(activityType);
      // Remaining types not started
      for (const rest of ACTIVITY_TYPES_FULL.slice(ACTIVITY_TYPES_FULL.indexOf(activityType) + 1)) {
        if (!incompleteTypes.includes(rest)) incompleteTypes.push(rest);
        if (!budgetHitTypes.includes(rest)) budgetHitTypes.push(rest);
      }
      break;
    }

    const pageResult = activityType === 'TRADE'
      ? await fetchActivityTimestamp(fetchImpl, address, activityType, { deadline, maxPagesPerType })
      : await fetchActivityOffset(fetchImpl, address, activityType, { deadline, maxPagesPerType });

    pages_fetched += pageResult.pages;
    if (pageResult.pagination_incomplete) incompleteTypes.push(activityType);
    if (pageResult.budget_hit) budgetHitTypes.push(activityType);

    if (activityType === 'TRADE') {
      for (const row of pageResult.items) {
        const usdc = toNumber(row.usdcSize);
        if (row.side === 'BUY') {
          total_buy += usdc;
          counts.buy_count += 1;
        } else if (row.side === 'SELL') {
          total_sell += usdc;
          counts.sell_count += 1;
        }
        counts.trade_count += 1;
      }
    } else if (activityType === 'REDEEM') {
      total_redeem = sumUsdc(pageResult.items);
      counts.redeem_count = pageResult.items.length;
    } else if (activityType === 'MERGE') {
      total_merge = sumUsdc(pageResult.items);
      counts.merge_count = pageResult.items.length;
    } else if (activityType === 'SPLIT') {
      total_split = sumUsdc(pageResult.items);
      counts.split_count = pageResult.items.length;
    } else if (activityType === 'MAKER_REBATE') {
      total_rebate = sumUsdc(pageResult.items);
      counts.rebate_count = pageResult.items.length;
    } else if (activityType === 'REWARD') {
      total_reward = sumUsdc(pageResult.items);
      counts.reward_count = pageResult.items.length;
    } else if (activityType === 'REFERRAL_REWARD') {
      total_referral = sumUsdc(pageResult.items);
      counts.referral_count = pageResult.items.length;
    } else if (activityType === 'CONVERSION') {
      total_conversion = sumUsdc(pageResult.items);
      counts.conversion_count = pageResult.items.length;
    }
  }

  const positionsResult = Date.now() < deadline
    ? await fetchAllPositions(fetchImpl, address, { deadline })
    : { items: [], truncated: true, budget_hit: true };
  if (positionsResult.budget_hit && !budgetHitTypes.includes('POSITIONS')) {
    budgetHitTypes.push('POSITIONS');
  }

  let unrealized = 0;
  let open_positions = 0;
  for (const p of positionsResult.items) {
    const size = toNumber(p.size);
    const curPrice = toNumber(p.curPrice);
    if (size > 0) {
      unrealized += size * curPrice;
      open_positions += 1;
    }
  }

  const pnl_trading = round2(
    total_sell + total_redeem + total_merge + total_rebate - total_buy - total_split + unrealized
  );
  const pnl_inclusive = round2(pnl_trading + total_reward + total_referral + total_conversion);
  const pagination_incomplete = incompleteTypes.length > 0 || positionsResult.truncated || budgetHitTypes.length > 0;
  const complete = !pagination_incomplete;

  return {
    status: complete ? 'complete' : 'incomplete',
    complete,
    pagination_incomplete,
    pagination_incomplete_types: incompleteTypes.length ? incompleteTypes : null,
    budget_hit_types: budgetHitTypes.length ? budgetHitTypes : null,
    positions_truncated: positionsResult.truncated,
    pages_fetched,
    formula: 'SELL+REDEEM+MERGE+REBATE - BUY - SPLIT + unrealized; inclusive += REWARD+REFERRAL+CONVERSION',
    totals: {
      total_buy: round2(total_buy),
      total_sell: round2(total_sell),
      total_redeem: round2(total_redeem),
      total_merge: round2(total_merge),
      total_split: round2(total_split),
      total_rebate: round2(total_rebate),
      total_reward: round2(total_reward),
      total_referral: round2(total_referral),
      total_conversion: round2(total_conversion),
      unrealized: round2(unrealized)
    },
    counts: { ...counts, open_positions },
    pnl_trading_usd: pnl_trading,
    pnl_inclusive_usd: pnl_inclusive,
    open_positions,
    source: 'data-api.polymarket.com/activity + /positions'
  };
}

async function fetchActivityOffset(fetchImpl, address, activityType, { deadline, maxPagesPerType }) {
  const items = [];
  let offset = 0;
  let pages = 0;
  let pagination_incomplete = false;
  let budget_hit = false;

  while (pages < maxPagesPerType) {
    if (Date.now() >= deadline) {
      budget_hit = true;
      pagination_incomplete = true;
      break;
    }
    const url = `${DATA_BASE}/activity?user=${address}&type=${activityType}&limit=${PAGE_LIMIT}&offset=${offset}&sortDirection=ASC`;
    const records = await fetchJson(fetchImpl, url).catch(() => []);
    pages += 1;
    if (!Array.isArray(records) || !records.length) break;
    items.push(...records);
    if (records.length < PAGE_LIMIT) break;
    offset += records.length;
    if (offset >= ACTIVITY_OFFSET_CAP) {
      pagination_incomplete = true;
      break;
    }
  }
  if (pages >= maxPagesPerType && items.length >= PAGE_LIMIT * maxPagesPerType) {
    pagination_incomplete = true;
  }
  return { items, pages, pagination_incomplete, budget_hit };
}

async function fetchActivityTimestamp(fetchImpl, address, activityType, { deadline, maxPagesPerType }) {
  const items = [];
  let end = null;
  let pages = 0;
  let pagination_incomplete = false;
  let budget_hit = false;

  while (pages < maxPagesPerType) {
    if (Date.now() >= deadline) {
      budget_hit = true;
      pagination_incomplete = true;
      break;
    }
    const endParam = end == null ? '' : `&end=${end}`;
    const url = `${DATA_BASE}/activity?user=${address}&type=${activityType}&limit=${PAGE_LIMIT}${endParam}`;
    const records = await fetchJson(fetchImpl, url).catch(() => []);
    pages += 1;
    if (!Array.isArray(records) || !records.length) break;
    items.push(...records);

    const timestamps = records.map((r) => Number(r.timestamp)).filter(Number.isFinite);
    if (!timestamps.length) break;
    const oldest = Math.min(...timestamps);
    const oldestCount = timestamps.filter((t) => t === oldest).length;

    // Same-second full-page boundary can lose rows; mark incomplete (Worker skips exact-second backfill).
    if (records.length === PAGE_LIMIT && oldestCount > 0) {
      pagination_incomplete = true;
    }

    const nextEnd = oldest - 1;
    if (nextEnd < 0 || records.length < PAGE_LIMIT) break;
    end = nextEnd;
  }

  if (pages >= maxPagesPerType) pagination_incomplete = true;
  return { items, pages, pagination_incomplete, budget_hit };
}

async function fetchAllPositions(fetchImpl, address, { deadline }) {
  const items = [];
  let offset = 0;
  let truncated = false;
  let budget_hit = false;

  while (true) {
    if (Date.now() >= deadline) {
      budget_hit = true;
      truncated = true;
      break;
    }
    const url = `${DATA_BASE}/positions?user=${address}&sizeThreshold=0&limit=${PAGE_LIMIT}&offset=${offset}`;
    const records = await fetchJson(fetchImpl, url).catch(() => []);
    if (!Array.isArray(records) || !records.length) break;
    items.push(...records);
    if (records.length < PAGE_LIMIT) break;
    offset += records.length;
    if (offset >= POSITIONS_OFFSET_CAP) {
      if (records.length === PAGE_LIMIT) truncated = true;
      break;
    }
  }
  return { items, truncated, budget_hit };
}

function sumUsdc(rows) {
  return (rows || []).reduce((sum, row) => sum + toNumber(row.usdcSize), 0);
}

async function resolveAddress(fetchImpl, raw) {
  if (EVM.test(raw)) {
    return { address: raw.toLowerCase(), resolved_via: 'evm_address', display_name: null };
  }
  const needle = raw.toLowerCase();
  // Leaderboard username search is best-effort (paged LB). Prefer 0x address for certainty.
  const maxPages = 6; // ~3000 rows; beyond this return unresolved (caller should pass 0x)
  for (let page = 0; page < maxPages; page++) {
    const rows = await fetchJson(
      fetchImpl,
      `${LB_BASE}/profit?window=all&limit=500&offset=${page * 500}`
    ).catch(() => []);
    if (!Array.isArray(rows) || !rows.length) break;
    for (const row of rows) {
      const name = String(row.name ?? '').toLowerCase();
      const pseudonym = String(row.pseudonym ?? '').toLowerCase();
      if (name === needle || pseudonym === needle) {
        const address = String(row.proxyWallet ?? '').toLowerCase();
        return {
          address: EVM.test(address) ? address : null,
          resolved_via: 'leaderboard_username',
          display_name: row.name ?? row.pseudonym ?? raw
        };
      }
    }
    if (rows.length < 500) break;
  }
  return { address: null, resolved_via: 'username_not_in_scanned_leaderboard', display_name: null };
}

function summarizeLeaderboard(rows, address) {
  const row = Array.isArray(rows) ? rows[0] : null;
  return {
    amount_usd: row?.amount != null ? round2(Number(row.amount)) : null,
    name: row?.name ?? row?.pseudonym ?? null,
    proxy_wallet: row?.proxyWallet ?? address,
    window: 'all',
    source: 'lb-api.polymarket.com/profit?window=all',
    row_found: Boolean(row)
  };
}

function summarizePositions(rows, limit) {
  const list = Array.isArray(rows) ? rows : [];
  const normalized = list.map((p) => ({
    title: p.title ?? p.slug ?? null,
    outcome: p.outcome ?? null,
    size: toNumber(p.size),
    avg_price: toNumber(p.avgPrice),
    cash_pnl: toNumber(p.cashPnl),
    current_value: toNumber(p.currentValue),
    condition_id: p.conditionId ?? null
  }));
  const total = normalized.reduce((sum, p) => sum + (p.cash_pnl || 0), 0);
  return {
    total_cash_pnl_usd: round2(total),
    positions_sampled: normalized.length,
    open_positions_sampled: normalized.filter((p) => Math.abs(p.size || 0) > 0).length,
    positions_limit: limit,
    positions_truncated: normalized.length >= limit,
    source: 'data-api.polymarket.com/positions cashPnl',
    sample: normalized.slice(0, 10)
  };
}

function computeDivergence(leaderboard, positions) {
  const lb = leaderboard.amount_usd;
  const pos = positions.total_cash_pnl_usd;
  if (!Number.isFinite(lb) || !Number.isFinite(pos)) {
    return {
      verdict: 'unknown',
      delta_usd: null,
      abs_delta_usd: null,
      threshold_usd: AUDIT_PASS_DELTA_USD,
      interpretation: 'Missing LB or position cashPnL layer.',
      compared_layer: 'positions_cash_pnl'
    };
  }
  const delta = round2(lb - pos);
  const absDelta = Math.abs(delta);
  let verdict = 'aligned';
  if (absDelta > AUDIT_PASS_DELTA_USD) {
    verdict = delta > 0 ? 'lb_optimistic' : 'replay_higher';
  }
  return {
    verdict,
    delta_usd: delta,
    abs_delta_usd: round2(absDelta),
    threshold_usd: AUDIT_PASS_DELTA_USD,
    compared_layer: 'positions_cash_pnl',
    interpretation: verdict === 'aligned'
      ? 'LB all-time and sampled position cashPnL are within the quick-audit threshold.'
      : (verdict === 'lb_optimistic'
        ? 'Leaderboard profit is materially higher than sampled position cashPnL; do not trust headline PnL without full replay.'
        : 'Position cashPnL proxy is materially higher than LB; full replay may exceed the headline or LB window may differ.')
  };
}

function computeReplayDivergence(leaderboard, replay) {
  const lb = leaderboard.amount_usd;
  const replayPnl = replay?.pnl_trading_usd;
  if (!Number.isFinite(lb) || !Number.isFinite(replayPnl)) {
    return {
      verdict: 'unknown',
      delta_usd: null,
      abs_delta_usd: null,
      threshold_usd: AUDIT_PASS_DELTA_USD,
      compared_layer: 'cashflow_replay',
      interpretation: 'Missing LB or cashflow replay PnL.'
    };
  }
  const delta = round2(lb - replayPnl);
  const absDelta = Math.abs(delta);
  let verdict = 'aligned';
  if (absDelta > AUDIT_PASS_DELTA_USD) {
    verdict = delta > 0 ? 'lb_optimistic' : 'replay_higher';
  }
  if (!replay.complete && verdict === 'aligned') {
    return {
      verdict: 'unknown',
      delta_usd: delta,
      abs_delta_usd: round2(absDelta),
      threshold_usd: AUDIT_PASS_DELTA_USD,
      compared_layer: 'cashflow_replay',
      interpretation: 'Replay incomplete; do not treat near-match as audit pass.'
    };
  }
  return {
    verdict,
    delta_usd: delta,
    abs_delta_usd: round2(absDelta),
    threshold_usd: AUDIT_PASS_DELTA_USD,
    compared_layer: 'cashflow_replay',
    pnl_inclusive_usd: replay.pnl_inclusive_usd,
    interpretation: verdict === 'aligned'
      ? 'LB all-time and cashflow-replay trading PnL are within the audit threshold.'
      : (verdict === 'lb_optimistic'
        ? 'Leaderboard profit is materially higher than cashflow replay; distrust headline claims for copy-trading.'
        : 'Cashflow replay exceeds LB; LB window/credits may differ — verify manually before trusting either.')
  };
}

function chooseAction(divergence, { positions_truncated, requestedMode, replayComplete }) {
  if (requestedMode === 'full') {
    if (!replayComplete) return 'verify_manually';
    if (divergence.verdict === 'aligned') return 'trust_for_copy';
    if (divergence.verdict === 'lb_optimistic' && (divergence.abs_delta_usd ?? 0) >= 100) {
      return 'distrust_claims';
    }
    return 'verify_manually';
  }
  // Quick is triage only: LB vs sampled position cashPnL. Never emit trust_for_copy
  // without a complete cashflow replay (mode=full).
  if (divergence.verdict === 'lb_optimistic' && (divergence.abs_delta_usd ?? 0) >= 100) {
    return 'distrust_claims';
  }
  if (divergence.verdict === 'aligned' && !positions_truncated) return 'quick_triage_ok';
  return 'verify_manually';
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

function normalizeMode(value) {
  const raw = String(value ?? 'quick').trim().toLowerCase();
  return raw === 'full' ? 'full' : 'quick';
}

function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

function buildBuyerSummaryZh({
  resolved, leaderboard_profit, positions_cash_pnl, divergence, action, cashflow_replay, requestedMode
}) {
  const who = leaderboard_profit.name || resolved.display_name || shorten(resolved.address);
  const lb = leaderboard_profit.amount_usd == null ? 'LB 无记录' : `LB all-time ${formatUsd(leaderboard_profit.amount_usd)}`;
  if (requestedMode === 'full' && cashflow_replay) {
    const replay = `回放 trading ${formatUsd(cashflow_replay.pnl_trading_usd)}`
      + (cashflow_replay.complete ? '' : '（incomplete）');
    return `${who}：${lb}；${replay}；verdict=${divergence.verdict}，action=${action}。`;
  }
  const pos = positions_cash_pnl.total_cash_pnl_usd == null
    ? '持仓 PnL 无记录'
    : `持仓 cashPnL ${formatUsd(positions_cash_pnl.total_cash_pnl_usd)}`;
  return `${who}：${lb}；${pos}；verdict=${divergence.verdict}，action=${action}。quick 不是完整流水审计。`;
}

function buildBuyerSummaryEn({
  resolved, leaderboard_profit, positions_cash_pnl, divergence, action, cashflow_replay, requestedMode
}) {
  const who = leaderboard_profit.name || resolved.display_name || shorten(resolved.address);
  const lb = leaderboard_profit.amount_usd == null ? 'LB missing' : `LB all-time ${formatUsd(leaderboard_profit.amount_usd)}`;
  if (requestedMode === 'full' && cashflow_replay) {
    const replay = `replay trading ${formatUsd(cashflow_replay.pnl_trading_usd)}`
      + (cashflow_replay.complete ? '' : ' (incomplete)');
    return `${who}: ${lb}; ${replay}; verdict=${divergence.verdict}, action=${action}.`;
  }
  const pos = positions_cash_pnl.total_cash_pnl_usd == null
    ? 'position cashPnL missing'
    : `position cashPnL ${formatUsd(positions_cash_pnl.total_cash_pnl_usd)}`;
  return `${who}: ${lb}; ${pos}; verdict=${divergence.verdict}, action=${action}. Quick mode is not full cashflow replay.`;
}

function formatUsd(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return 'n/a';
  return `${n >= 0 ? '+' : '-'}$${Math.abs(n).toFixed(2)}`;
}

function shorten(address) {
  const value = String(address ?? '');
  if (!value.startsWith('0x') || value.length < 12) return value || 'wallet';
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}
