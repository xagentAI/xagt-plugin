// Musk tweet-count category plugin (L1) for PM Event Readout.
// Framework: research/2026-07-09-pm-event-analyst-framework.md
// Adds ladder distribution + optional count snapshot. No Leo relay, no orders, no sizing.

import { round2 } from './pm-gamma-market.mjs';

/**
 * @param {object} args
 * @param {object} args.market primary normalized market
 * @param {object|null} args.eventBundle
 * @param {object[]} args.eventMatrix from L0
 * @param {object} [args.snapshot] { current_count, hours_left, window_time, window_label, recent_6h, recent_12h }
 */
export function enrichMuskCategory({ market, eventBundle, eventMatrix, snapshot = null }) {
  const buckets = (eventMatrix || []).map((row) => {
    const label = normalizeBucketLabel(row.group_item_title || row.title);
    return {
      bucket: label,
      slug: row.slug,
      yes: row.yes,
      volume_24h_usd: row.volume_24h_usd,
      best_ask: row.best_ask,
      best_bid: row.best_bid,
      spread: row.spread,
      is_primary: row.is_primary
    };
  }).sort(compareBuckets);

  const yesSum = buckets.reduce((sum, b) => sum + (Number.isFinite(b.yes) ? b.yes : 0), 0);
  const market_implied_distribution = buckets.map((b) => ({
    bucket: b.bucket,
    yes: b.yes,
    share_of_yes_mass: yesSum > 0 && Number.isFinite(b.yes) ? round2(b.yes / yesSum) : null
  }));

  const modal = buckets
    .filter((b) => Number.isFinite(b.yes))
    .slice()
    .sort((a, b) => b.yes - a.yes)[0] ?? null;

  const count = snapshot && Number.isFinite(Number(snapshot.current_count))
    ? Number(snapshot.current_count)
    : null;
  const hoursLeft = snapshot && Number.isFinite(Number(snapshot.hours_left))
    ? Number(snapshot.hours_left)
    : null;

  const pace = buildPaceNotes(count, hoursLeft, snapshot);
  const countVsLadder = buildCountVsLadder(count, buckets, modal);
  const thesis = buildThesis(modal, count, countVsLadder, yesSum);

  const freshness = snapshot?.snapshot_time || count !== null
    ? {
        status: count !== null ? 'provided' : 'missing',
        snapshot_time: snapshot?.snapshot_time ?? null,
        detail: count !== null
          ? 'Caller-provided count snapshot; ASP does not scrape X.'
          : 'Pass musk.current_count (+ hours_left) for pace notes; ASP does not scrape X.'
      }
    : { status: 'missing', snapshot_time: null, detail: 'Pass musk.current_count (+ hours_left) for pace notes; ASP does not scrape X.' };

  // Without a live count, ladder shape alone must not look highly tradable.
  const tradability_cap = count === null ? 'medium' : null;
  const tradability_reasons = count === null
    ? ['musk_count_snapshot_missing']
    : [];

  const plugin = {
    category: 'musk',
    category_depth: 'enriched',
    window: snapshot?.window_label || eventBundle?.title || market?.title || null,
    count_source_freshness: freshness,
    current_count: count,
    hours_left: hoursLeft,
    recent_6h: snapshot?.recent_6h ?? null,
    recent_12h: snapshot?.recent_12h ?? null,
    full_bucket_surface: buckets,
    market_implied_distribution,
    yes_mass_sum: round2(yesSum),
    modal_bucket: modal ? { bucket: modal.bucket, yes: modal.yes, slug: modal.slug } : null,
    pace_notes: pace,
    count_vs_ladder: countVsLadder,
    direct_bucket_thesis: thesis,
    split_ladder_paper: {
      status: 'not_computed_in_asp_v1',
      detail: 'Paper split-ladder / bankroll sizing stays in local pm-musk-count skill; ASP returns ladder + count context only.'
    },
    default_action_hint: 'use_decision_card_or_local_skill_for_size',
    hard_gate: 'no_orders_no_account_mutation_no_leo_bankroll',
    tradability_cap,
    tradability_reasons
  };

  plugin.batch2_public = toMuskBatch2PublicCard(plugin, {
    matrix_status: buckets.length >= 3 ? 'complete' : 'incomplete',
    event_slug: eventBundle?.slug || null,
    market_slug: market?.slug || modal?.slug || null
  });

  return plugin;
}

/**
 * Map Musk L1 plugin → Batch 2 shared public schema
 * (research/2026-07-09-pm-category-analyst-batch2-brief.md).
 * Never emits bankroll / leo_private / order instructions.
 */
export function toMuskBatch2PublicCard(plugin, meta = {}) {
  const countMissing = plugin?.count_source_freshness?.status === 'missing' || plugin?.current_count == null;
  const modal = plugin?.modal_bucket || null;
  const mapped = plugin?.count_vs_ladder?.matching_buckets?.[0] || null;
  const yesMass = Number(plugin?.yes_mass_sum);
  const risk_flags = [];
  if (countMissing) risk_flags.push('count_snapshot_missing');
  if (Number.isFinite(yesMass) && (yesMass > 1.15 || yesMass < 0.85)) {
    risk_flags.push('yes_mass_not_exclusive');
  }
  if (plugin?.count_vs_ladder?.status === 'unmapped') risk_flags.push('count_unmapped_to_ladder');
  if (mapped && modal && mapped.bucket !== modal.bucket) {
    risk_flags.push('count_bucket_diverges_from_modal');
  }

  // ASP is analysis-only: never return "trade" as a tip.
  let action = 'watch';
  if (countMissing) action = 'skip';
  else if (plugin?.hours_left != null && Number(plugin.hours_left) <= 0) action = 'no_trade';

  const confidence = countMissing
    ? 0.25
    : (mapped && modal && mapped.bucket === modal.bucket ? 0.55 : 0.4);

  const window = plugin?.window || 'musk-window';
  const snap = plugin?.count_source_freshness?.snapshot_time || 'no-snap';
  const postmortem_key = [
    meta.event_slug || 'musk-event',
    String(window).replace(/\s+/g, '_').slice(0, 48),
    snap
  ].join('|');

  return {
    category: 'musk',
    fixture_status: countMissing ? 'failed_or_unverified' : 'ok',
    matrix_status: meta.matrix_status || (plugin?.full_bucket_surface?.length >= 3 ? 'complete' : 'incomplete'),
    market_implied_shape: {
      modal_bucket: modal,
      distribution: plugin?.market_implied_distribution || [],
      yes_mass_sum: plugin?.yes_mass_sum ?? null,
      count_vs_ladder: plugin?.count_vs_ladder || null
    },
    thesis: plugin?.direct_bucket_thesis || '',
    best_expression: modal
      ? {
          market: modal.slug || modal.bucket,
          side: 'Yes',
          why: mapped && mapped.bucket !== modal.bucket
            ? `Market modal is ${modal.bucket}, but live count maps to ${mapped.bucket} — expression is shape context only, not a tip.`
            : `Highest Yes-mass bucket on the ladder: ${modal.bucket} @ ${modal.yes}. Not a buy tip.`
        }
      : { market: '', side: '', why: 'No modal bucket available.' },
    action,
    confidence,
    risk_flags,
    caveats: [
      'ASP Musk card is ladder + optional caller count only; does not scrape X.',
      'action never means place an order — use local decision-card / manual gate.',
      ...(plugin?.pace_notes || [])
    ],
    postmortem_key,
    next_gate: 'Use_pm_trade_preflight_or_manual_decision_card_before_orders'
  };
}

export function extractMuskSnapshot(input = {}, options = {}) {
  if (options.muskSnapshot && typeof options.muskSnapshot === 'object') {
    return options.muskSnapshot;
  }
  const raw = input.musk && typeof input.musk === 'object' ? input.musk : input;
  const count = raw.current_count ?? raw.count ?? null;
  if (count === null || count === undefined || count === '') return null;
  return {
    current_count: Number(count),
    hours_left: raw.hours_left != null ? Number(raw.hours_left) : null,
    snapshot_time: raw.snapshot_time ?? raw.as_of ?? null,
    window_label: raw.window_label ?? raw.window ?? null,
    recent_6h: raw.recent_6h != null ? Number(raw.recent_6h) : null,
    recent_12h: raw.recent_12h != null ? Number(raw.recent_12h) : null
  };
}

function normalizeBucketLabel(raw) {
  const text = String(raw ?? '').trim();
  if (!text) return 'unknown';
  // "160-179", "<20", "240+", "40-59"
  const range = text.match(/(\d+)\s*[-–]\s*(\d+)/);
  if (range) return `${range[1]}-${range[2]}`;
  const lt = text.match(/<\s*(\d+)/) || text.match(/(\d+)\s*or below/i);
  if (lt) return `<${lt[1]}`;
  const plus = text.match(/(\d+)\s*\+/);
  if (plus) return `${plus[1]}+`;
  return text;
}

function parseBucketBounds(label) {
  const s = String(label);
  if (s.startsWith('<')) {
    const n = Number(s.slice(1));
    return Number.isFinite(n) ? { lo: 0, hi: n - 1, sort: n } : null;
  }
  if (s.endsWith('+')) {
    const n = Number(s.slice(0, -1));
    return Number.isFinite(n) ? { lo: n, hi: Infinity, sort: n } : null;
  }
  const m = s.match(/^(\d+)-(\d+)$/);
  if (m) return { lo: Number(m[1]), hi: Number(m[2]), sort: Number(m[1]) };
  return null;
}

function compareBuckets(a, b) {
  const ba = parseBucketBounds(a.bucket);
  const bb = parseBucketBounds(b.bucket);
  if (ba && bb) return ba.sort - bb.sort;
  return String(a.bucket).localeCompare(String(b.bucket));
}

function buildPaceNotes(count, hoursLeft, snapshot) {
  if (count === null) {
    return ['No current_count provided — market ladder only; pace unknown.'];
  }
  const notes = [`Current count snapshot: ${count}.`];
  if (hoursLeft === null) {
    notes.push('hours_left missing — cannot pace remaining window.');
  } else if (hoursLeft <= 0) {
    notes.push('Window appears ended or hours_left≤0 — treat as settlement/lock-in regime, not fresh pace.');
  } else {
    notes.push(`Hours left (caller-provided): ${hoursLeft}.`);
    if (snapshot?.recent_6h != null) notes.push(`Recent 6h count delta: ${snapshot.recent_6h}.`);
    if (snapshot?.recent_12h != null) notes.push(`Recent 12h count delta: ${snapshot.recent_12h}.`);
  }
  return notes;
}

function buildCountVsLadder(count, buckets, modal) {
  if (count === null) {
    return {
      status: 'no_count',
      matching_buckets: [],
      note: 'Provide musk.current_count to map count into ladder buckets.'
    };
  }
  const matching = buckets.filter((b) => {
    const bounds = parseBucketBounds(b.bucket);
    if (!bounds) return false;
    return count >= bounds.lo && count <= bounds.hi;
  });
  return {
    status: matching.length ? 'mapped' : 'unmapped',
    matching_buckets: matching.map((b) => ({ bucket: b.bucket, yes: b.yes, slug: b.slug })),
    modal_bucket: modal?.bucket ?? null,
    note: matching.length
      ? `Count ${count} sits in bucket(s): ${matching.map((b) => b.bucket).join(', ')}.`
      : `Count ${count} did not map to a parsed bucket label — check ladder naming.`
  };
}

function buildThesis(modal, count, countVsLadder, yesSum) {
  const parts = [];
  if (modal) {
    parts.push(`Market modal bucket by Yes mass: ${modal.bucket} @ ${modal.yes}.`);
  }
  if (yesSum > 1.15 || yesSum < 0.85) {
    parts.push(`Yes-mass sum across buckets is ${round2(yesSum)} (neg-risk ladders often ≠ 1; do not treat as exclusive probs).`);
  }
  if (count !== null && countVsLadder?.matching_buckets?.length) {
    const m = countVsLadder.matching_buckets[0];
    parts.push(`Live count maps to ${m.bucket} (market Yes ${m.yes}) — compare to modal before any size decision.`);
  } else if (count === null) {
    parts.push('Without live count, this is ladder shape only — not a pace edge.');
  }
  parts.push('Not a buy tip; use local pm-musk-count / decision-card for action and size.');
  return parts.join(' ');
}
