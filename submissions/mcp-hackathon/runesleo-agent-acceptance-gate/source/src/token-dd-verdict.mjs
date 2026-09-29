// Token DD Verdict (token_dd_verdict) — Quick-tier rule-based research gate.
// Maps asset-dd participation buckets to a compact API verdict. Not LLM judging;
// optional DexScreener public lookup for EVM contract addresses only.

const SERVICE_ID = 'token_dd_verdict';
const DEXSCREENER_BASE = 'https://api.dexscreener.com/latest/dex/tokens';
const FETCH_TIMEOUT_MS = 8000;

const REFERRAL_PATTERNS = [
  /\brise\.rich\/ref\//i,
  /\bref=[\w-]{4,}/i,
  /\baffiliate\b/i,
  /\binvite\.code\b/i,
  /\bairdrop\b.*\bclaim\b/i
];

const EVM_ADDRESS = /\b(0x[a-fA-F0-9]{40})\b/;
const TICKER_ONLY = /^[A-Za-z][A-Za-z0-9]{1,14}$/;

const STANDARD_CAVEATS = [
  'Rule-based Standard-lite research gate. Not investment advice, not a security audit, not LLM-generated research.',
  'No wallet custody, no trade execution, no order routing.',
  'Still not Full institutional DD (asset-dd); honeypot/owner/unlocks need deeper escrow or human review.'
];

/**
 * Live quick verdict. Throws when DexScreener is required but unreachable for a
 * contract-only input with no other anchors.
 */
export async function assessTokenDdVerdictLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const raw = String(input.asset ?? input.token ?? input.query ?? '').trim();
  if (!raw) {
    throw new Error('asset (ticker, contract address, or URL) is required');
  }

  const parsed = parseAssetInput(raw);
  const pillars = buildPillarBaseline();
  const hardStops = [];
  const reasons = [];

  if (parsed.referral_risk) {
    applyPillar(pillars, 'referral_and_promo_risk', 'fail', 'Referral or promo wrapper detected before canonical asset id.');
    hardStops.push('referral_or_promo_wrapper');
    reasons.push('Input looks like a referral/promo link without a reliable tradable identifier.');
  }

  if (!parsed.canonical_id) {
    applyPillar(pillars, 'identifier_clarity', 'fail', 'No canonical ticker or on-chain identifier extracted.');
    hardStops.push('missing_canonical_identifier');
    reasons.push('Could not extract a ticker or contract/mint address to research.');
  } else {
    applyPillar(pillars, 'identifier_clarity', 'pass', `Canonical id: ${parsed.canonical_id} (${parsed.id_type}).`);
  }

  let dexContext = null;
  const confidenceGaps = [];
  const hardVetoGaps = [];

  if (parsed.evm_contract) {
    dexContext = await fetchDexScreenerPairs(fetchImpl, parsed.evm_contract).catch(() => null);
    if (!dexContext) {
      applyPillar(pillars, 'liquidity_and_market_presence', 'warn', 'DexScreener lookup failed or returned no pairs.');
      reasons.push('On-chain liquidity could not be verified from public DEX data.');
      confidenceGaps.push('dex_lookup_failed');
    } else if (!dexContext.pairs.length) {
      applyPillar(pillars, 'liquidity_and_market_presence', 'fail', 'No DEX pairs found for contract.');
      hardStops.push('no_public_dex_liquidity');
      reasons.push('No public DEX liquidity pairs found for this contract.');
    } else {
      const top = dexContext.pairs[0];
      applyPillar(
        pillars,
        'liquidity_and_market_presence',
        top.liquidity_usd >= 50_000 ? 'pass' : 'warn',
        `Top pair liquidity ~$${Math.round(top.liquidity_usd).toLocaleString('en-US')} on ${top.dexId}/${top.chainId}.`
      );
      if (top.liquidity_usd < 10_000) {
        hardStops.push('very_low_liquidity');
        reasons.push('Top DEX pair liquidity is very low (<$10k).');
      }

      // Standard-lite: activity / age / volatility proxies from pair stats
      applyPillar(
        pillars,
        'market_activity',
        top.volume_h24 >= 25_000 ? 'pass' : (top.volume_h24 >= 2_000 ? 'warn' : 'fail'),
        `24h volume ~$${Math.round(top.volume_h24).toLocaleString('en-US')}.`
      );
      if (top.volume_h24 < 500) {
        hardStops.push('negligible_24h_volume');
        reasons.push('24h DEX volume is negligible.');
      }

      const ageHours = top.pair_created_at
        ? Math.max(0, (Date.now() - top.pair_created_at) / 3_600_000)
        : null;
      applyPillar(
        pillars,
        'venue_maturity',
        ageHours === null ? 'neutral' : (ageHours >= 24 * 14 ? 'pass' : (ageHours >= 24 ? 'warn' : 'fail')),
        ageHours === null
          ? 'Pair age unavailable from DexScreener.'
          : `Top pair age ~${Math.round(ageHours)}h.`
      );
      if (ageHours !== null && ageHours < 6) {
        hardStops.push('brand_new_pair');
        reasons.push('Top pair is extremely new (<6h); rug / sniper risk elevated.');
      }

      const absChange = Math.abs(top.price_change_h24 ?? 0);
      applyPillar(
        pillars,
        'volatility_proxy',
        absChange >= 80 ? 'warn' : 'pass',
        `24h price change ~${round1(top.price_change_h24)}%.`
      );
      if (absChange >= 150) {
        reasons.push('Extreme 24h price move — treat as speculative.');
      }

      // Holder concentration not available on DexScreener free path
      applyPillar(pillars, 'holder_concentration_proxy', 'neutral',
        'Holder concentration / top-10% not available on this public path.');
      confidenceGaps.push('holder_distribution_unavailable');
      hardVetoGaps.push('no_honeypot_tax_owner_scan');
    }
  } else if (parsed.id_type === 'ticker') {
    applyPillar(pillars, 'liquidity_and_market_presence', 'neutral', 'Ticker-only scan; no contract-level liquidity check.');
    applyPillar(pillars, 'market_activity', 'neutral', 'Ticker-only — skip DEX activity.');
    applyPillar(pillars, 'venue_maturity', 'neutral', 'Ticker-only — skip pair age.');
    applyPillar(pillars, 'volatility_proxy', 'neutral', 'Ticker-only — skip pair volatility.');
    applyPillar(pillars, 'holder_concentration_proxy', 'neutral', 'Ticker-only — skip holders.');
    reasons.push('Major ticker symbol without contract — use contract address for deeper on-chain checks.');
    reasons.push('Ticker-only inputs are capped at research_position; conviction requires a contract-level scan.');
    confidenceGaps.push('ticker_only_no_contract');
    hardVetoGaps.push('no_contract_security_scan');
  } else {
    applyPillar(pillars, 'liquidity_and_market_presence', 'neutral', 'Non-EVM or unresolved identifier; skips automated DEX scan.');
    applyPillar(pillars, 'market_activity', 'neutral', 'Skipped.');
    applyPillar(pillars, 'venue_maturity', 'neutral', 'Skipped.');
    applyPillar(pillars, 'volatility_proxy', 'neutral', 'Skipped.');
    applyPillar(pillars, 'holder_concentration_proxy', 'neutral', 'Skipped.');
    confidenceGaps.push('unresolved_identifier');
  }

  applyPillar(pillars, 'security_heuristics', parsed.evm_contract ? 'warn' : 'neutral',
    parsed.evm_contract
      ? 'Standard-lite still does not run honeypot/tax/owner permission scanners; contract presence + venue heuristics only.'
      : 'No contract-level security scan without an EVM address.');
  if (parsed.evm_contract) hardVetoGaps.push('no_honeypot_tax_owner_scan');

  applyPillar(pillars, 'narrative_hype_risk',
    parsed.referral_risk ? 'fail' : (/\b(moon|100x|gem|alpha group)\b/i.test(raw) ? 'warn' : 'pass'),
    parsed.referral_risk ? 'Promo/referral language in input.' : 'No obvious hype phrases in raw input.');

  applyPillar(pillars, 'tokenomics_unlock_gap', 'neutral',
    'Unlock schedule / emissions not checked in this endpoint — treat as unknown.');
  confidenceGaps.push('tokenomics_unlocks_unchecked');

  const score = scoreFromPillars(pillars, hardStops);
  let verdict_bucket = bucketFromScore(score, hardStops);
  // Ticker-only must not claim conviction — no contract liquidity/security scan.
  if (parsed.id_type === 'ticker' && (verdict_bucket === 'conviction' || verdict_bucket === 'tiny_speculative')) {
    verdict_bucket = 'research_position';
  }

  const dex_scan = dexContext
    ? {
        pairs_found: dexContext.pairs.length,
        top_pair: dexContext.pairs[0] ?? null,
        venue_depth_cap_usd: dexContext.pairs[0]?.liquidity_usd ?? null
      }
    : null;

  return {
    schema_version: '0.2',
    service_id: SERVICE_ID,
    mode: 'live',
    tier: 'standard_lite',
    generated_at: new Date().toISOString(),
    input: {
      asset: raw,
      canonical_id: parsed.canonical_id,
      id_type: parsed.id_type,
      asset_class: parsed.evm_contract ? 'evm_token' : (parsed.id_type === 'ticker' ? 'ticker_symbol' : 'unknown')
    },
    verdict_bucket,
    score_0_100: score,
    buyer_summary_zh: buildTokenBuyerSummaryZh(verdict_bucket, score, hardStops, dex_scan),
    pillars: pillarsToArray(pillars),
    hard_stops: hardStops,
    hard_veto_gaps: [...new Set(hardVetoGaps)],
    confidence_gaps: [...new Set(confidenceGaps)],
    reasons,
    dex_scan,
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: {
      method: 'rule_based_standard_lite_dd',
      dex_provider: parsed.evm_contract ? 'dexscreener_public_api' : null
    }
  };
}

export function buildTokenDdVerdictFallback(input = {}) {
  const raw = String(input?.asset ?? input?.token ?? '0x000000000000000000000000000000000000dead').trim();
  return {
    schema_version: '0.2',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    tier: 'standard_lite',
    generated_at: new Date().toISOString(),
    input: { asset: raw, canonical_id: null, id_type: 'unknown', asset_class: 'unknown' },
    verdict_bucket: 'watch_only',
    score_0_100: 45,
    pillars: pillarsToArray(buildPillarBaseline()),
    hard_stops: ['live_data_unavailable'],
    hard_veto_gaps: ['live_data_unavailable'],
    confidence_gaps: ['live_data_unavailable'],
    reasons: ['Live token lookup unavailable; serving static demo verdict only.'],
    dex_scan: null,
    caveats: [
      ...STANDARD_CAVEATS,
      'Demo mode: do not use for trading decisions.'
    ],
    next_gate: 'OKX_ASP_listing_changes_require_Leo_approval',
    source: { method: 'static_fallback' }
  };
}

function parseAssetInput(raw) {
  const referral_risk = REFERRAL_PATTERNS.some((pattern) => pattern.test(raw));
  const evmMatch = raw.match(EVM_ADDRESS);
  if (evmMatch) {
    return {
      referral_risk,
      canonical_id: evmMatch[1].toLowerCase(),
      id_type: 'evm_contract',
      evm_contract: evmMatch[1].toLowerCase()
    };
  }

  try {
    const url = new URL(raw);
    const path = `${url.pathname}${url.search}`;
    if (REFERRAL_PATTERNS.some((pattern) => pattern.test(path))) {
      return { referral_risk: true, canonical_id: null, id_type: 'unknown', evm_contract: null };
    }
    const fromPath = path.match(EVM_ADDRESS);
    if (fromPath) {
      return {
        referral_risk,
        canonical_id: fromPath[1].toLowerCase(),
        id_type: 'evm_contract',
        evm_contract: fromPath[1].toLowerCase()
      };
    }
  } catch {
    // not a URL
  }

  const ticker = raw.replace(/[^A-Za-z0-9]/g, '');
  if (TICKER_ONLY.test(ticker)) {
    return {
      referral_risk,
      canonical_id: ticker.toUpperCase(),
      id_type: 'ticker',
      evm_contract: null
    };
  }

  return { referral_risk, canonical_id: null, id_type: 'unknown', evm_contract: null };
}

function buildPillarBaseline() {
  return {
    identifier_clarity: pillar('identifier_clarity', 'Can we identify the tradable object?'),
    referral_and_promo_risk: pillar('referral_and_promo_risk', 'Referral/promo wrapper risk'),
    liquidity_and_market_presence: pillar('liquidity_and_market_presence', 'Public liquidity / market presence'),
    market_activity: pillar('market_activity', '24h venue activity / volume'),
    venue_maturity: pillar('venue_maturity', 'Pair / venue age proxy'),
    volatility_proxy: pillar('volatility_proxy', 'Short-horizon price volatility'),
    holder_concentration_proxy: pillar('holder_concentration_proxy', 'Holder concentration (if available)'),
    security_heuristics: pillar('security_heuristics', 'Automated security scan depth'),
    narrative_hype_risk: pillar('narrative_hype_risk', 'Hype / social pressure signals in input'),
    tokenomics_unlock_gap: pillar('tokenomics_unlock_gap', 'Unlock / emissions evidence gap')
  };
}

function pillar(id, label) {
  return { id, label, status: 'neutral', note: 'Pending evaluation.' };
}

function applyPillar(pillars, id, status, note) {
  if (!pillars[id]) return;
  pillars[id].status = status;
  pillars[id].note = note;
}

function pillarsToArray(pillars) {
  return Object.values(pillars).map((entry) => ({
    id: entry.id,
    label: entry.label,
    status: mapStatusEmoji(entry.status),
    note: entry.note
  }));
}

function mapStatusEmoji(status) {
  if (status === 'pass') return '✅';
  if (status === 'warn' || status === 'neutral') return '⚠️';
  if (status === 'fail') return '➖';
  return '⚠️';
}

function scoreFromPillars(pillars, hardStops) {
  if (hardStops.includes('referral_or_promo_wrapper') || hardStops.includes('missing_canonical_identifier')) {
    return 15;
  }
  let score = 55;
  for (const entry of Object.values(pillars)) {
    if (entry.status === 'pass') score += 8;
    if (entry.status === 'warn' || entry.status === 'neutral') score += 2;
    if (entry.status === 'fail') score -= 18;
  }
  if (hardStops.includes('no_public_dex_liquidity')) score = Math.min(score, 25);
  if (hardStops.includes('very_low_liquidity')) score = Math.min(score, 35);
  return clamp(Math.round(score), 0, 100);
}

function bucketFromScore(score, hardStops) {
  if (hardStops.includes('referral_or_promo_wrapper') || hardStops.includes('missing_canonical_identifier')) {
    return 'avoid';
  }
  if (hardStops.includes('no_public_dex_liquidity') || score < 30) return 'avoid';
  if (score < 45) return 'watch_only';
  if (score < 60) return 'research_position';
  if (score < 75) return 'tiny_speculative';
  return 'conviction';
}

async function fetchDexScreenerPairs(fetchImpl, contract) {
  const payload = await fetchJson(fetchImpl, `${DEXSCREENER_BASE}/${contract}`);
  const pairs = (Array.isArray(payload?.pairs) ? payload.pairs : [])
    .map((pair) => ({
      chainId: pair.chainId ?? null,
      dexId: pair.dexId ?? null,
      pairAddress: pair.pairAddress ?? null,
      liquidity_usd: toNumber(pair?.liquidity?.usd),
      volume_h24: toNumber(pair?.volume?.h24),
      priceUsd: toNumber(pair?.priceUsd),
      price_change_h24: toNumber(pair?.priceChange?.h24),
      txns_h24: toNumber(pair?.txns?.h24?.buys) + toNumber(pair?.txns?.h24?.sells),
      pair_created_at: pair?.pairCreatedAt ? toNumber(pair.pairCreatedAt) : null
    }))
    .filter((pair) => pair.liquidity_usd > 0)
    .sort((a, b) => b.liquidity_usd - a.liquidity_usd);
  return { pairs };
}

function round1(value) {
  return Math.round(toNumber(value) * 10) / 10;
}

async function fetchJson(fetchImpl, url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, {
      signal: controller.signal,
      headers: { accept: 'application/json' }
    });
    if (!response.ok) {
      throw new Error(`Upstream ${response.status} for ${url}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function buildTokenBuyerSummaryZh(bucket, score, hardStops, dexScan) {
  const bucketZh = {
    avoid: '避开',
    watch_only: '只观望',
    research_position: '可研究',
    tiny_speculative: '极小仓试错',
    conviction: '高信念（仍非建议）'
  }[bucket] || bucket;
  const stopBit = hardStops?.length ? `；硬停 ${hardStops.slice(0, 2).join(', ')}` : '';
  const liq = dexScan?.venue_depth_cap_usd;
  const liqBit = liq != null ? `；顶池流动性约 $${Math.round(liq).toLocaleString('en-US')}` : '';
  return `分桶 ${bucketZh}，分数 ${score}/100${stopBit}${liqBit}。Standard-lite 规则闸门，非审计/非投资建议。`;
}
