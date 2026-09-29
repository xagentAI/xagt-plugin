// Weather temperature-ladder category plugin (L1) for PM Event Readout.
// Public ASP surface: Gamma ladder + optional caller forecast/obs snapshot.
// No station scrape, no orders, no bankroll sizing (local skill only).

import { round2 } from './pm-gamma-market.mjs';

/**
 * @param {object} args
 * @param {object} args.market
 * @param {object|null} args.eventBundle
 * @param {object[]} args.eventMatrix
 * @param {object} [args.snapshot]
 *   { city, station, snapshot_time, observed_temp_c|f, forecast_mode_bucket,
 *     forecast_distribution:[{bucket,prob}], source_label }
 */
export function enrichWeatherCategory({ market, eventBundle, eventMatrix, snapshot = null }) {
  const buckets = (eventMatrix || []).map((row) => {
    const label = normalizeTempBucket(row.group_item_title || row.title || row.slug);
    return {
      bucket: label,
      slug: row.slug,
      yes: row.yes,
      volume_24h_usd: row.volume_24h_usd,
      best_ask: row.best_ask,
      best_bid: row.best_bid,
      spread: row.spread,
      is_primary: row.is_primary,
      temp_c: parseTempC(label)
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

  const freshness = buildFreshness(snapshot);
  const forecast = normalizeForecast(snapshot?.forecast_distribution);
  const observed = readObserved(snapshot);
  const thesis = buildThesis({ modal, forecast, observed, yesSum, buckets });
  const ladder_status = buckets.length >= 4 ? 'complete' : (buckets.length >= 2 ? 'thin' : 'incomplete');
  const adjacent_ladder = buildAdjacentLadderDiagnostics(buckets, modal);
  const hard_veto_gaps = buildWeatherHardVetoGaps({
    snapshot,
    freshness,
    observed,
    ladder_status,
    buckets,
    yesSum
  });

  const tradability_cap = hard_veto_gaps.length
    ? 'weak'
    : (freshness.status !== 'provided' ? 'medium' : null);
  const tradability_reasons = [];
  if (freshness.status !== 'provided') tradability_reasons.push('weather_source_snapshot_missing');
  if (ladder_status !== 'complete') tradability_reasons.push('weather_ladder_thin');
  if (hard_veto_gaps.length) tradability_reasons.push('weather_hard_veto_gaps');

  return {
    category: 'weather',
    category_depth: 'enriched',
    city: snapshot?.city || extractCity(eventBundle?.title || market?.title) || null,
    station: snapshot?.station ?? null,
    station_coordinates: snapshot?.station_coordinates ?? null,
    count_source_freshness: freshness,
    source_label: snapshot?.source_label ?? null,
    observed_temp: observed,
    ladder_status,
    matrix_completeness: {
      status: ladder_status === 'complete' ? 'complete' : 'incomplete',
      bucket_count: buckets.length,
      hard_veto_gaps
    },
    hard_veto_gaps,
    adjacent_ladder,
    full_bucket_surface: buckets,
    market_implied_distribution,
    yes_mass_sum: round2(yesSum),
    modal_bucket: modal ? { bucket: modal.bucket, yes: modal.yes, slug: modal.slug } : null,
    forecast_distribution: forecast,
    forecast_vs_market: compareForecastToMarket(forecast, buckets),
    direct_bucket_thesis: thesis,
    split_ladder_paper: {
      status: 'not_computed_in_asp_v1',
      detail: 'Paper split-ladder / bankroll stays in local pm-weather-ladder skill; ASP returns ladder + optional forecast context only.'
    },
    default_action_hint: hard_veto_gaps.length || tradability_reasons.length
      ? 'no_trade_until_source_and_ladder_ok'
      : 'use_decision_card_or_local_weather_skill',
    hard_gate: 'no_orders_no_account_mutation_no_station_scrape',
    tradability_cap,
    tradability_reasons,
    skill_alignment: {
      source: 'pm-weather-ladder',
      included: [
        'full_bucket_surface',
        'market_implied_distribution',
        'optional_forecast_distribution',
        'source_freshness_gate',
        'hard_veto_gaps',
        'adjacent_ladder_diagnostics'
      ],
      excluded_local_only: [
        'station_scrape',
        'bankroll_pct',
        'split_ladder_paper_execution',
        'u_amount_from_latest_anchor'
      ]
    }
  };
}

function buildWeatherHardVetoGaps({ snapshot, freshness, observed, ladder_status, buckets, yesSum }) {
  const gaps = [];
  if (!snapshot?.station) gaps.push('station_identity_missing');
  if (!snapshot?.station_coordinates && !snapshot?.station) gaps.push('station_coordinates_missing');
  if (freshness.status !== 'provided') gaps.push('source_snapshot_missing');
  if (!observed) gaps.push('observed_temp_missing');
  if (ladder_status === 'incomplete') gaps.push('ladder_incomplete');
  if (ladder_status === 'thin') gaps.push('ladder_thin');
  if (buckets.length && (yesSum > 1.2 || yesSum < 0.8)) gaps.push('yes_mass_incoherent');
  return gaps;
}

function buildAdjacentLadderDiagnostics(buckets, modal) {
  if (!buckets.length) {
    return { status: 'unavailable', note: 'No temperature buckets on surface.' };
  }
  const ordered = buckets.slice().sort(compareBuckets);
  const modalIdx = modal
    ? ordered.findIndex((b) => b.bucket === modal.bucket || b.slug === modal.slug)
    : -1;
  const adjacent = modalIdx >= 0
    ? ordered.slice(Math.max(0, modalIdx - 1), modalIdx + 2)
    : ordered.slice(0, 3);
  return {
    status: ordered.length >= 3 ? 'ok' : 'thin',
    modal_index: modalIdx,
    adjacent_buckets: adjacent.map((b) => ({
      bucket: b.bucket,
      yes: b.yes,
      ask: b.best_ask,
      slug: b.slug
    })),
    note: 'Exact-degree buckets are mutually exclusive; always read adjacent buckets with the modal.'
  };
}

export function extractWeatherSnapshot(input = {}, options = {}) {
  if (options.weatherSnapshot && typeof options.weatherSnapshot === 'object') {
    return options.weatherSnapshot;
  }
  const w = input.weather;
  if (w && typeof w === 'object') return w;
  return null;
}

function buildFreshness(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') {
    return {
      status: 'missing',
      snapshot_time: null,
      detail: 'Pass weather.snapshot_time + observed/forecast fields; ASP does not scrape METAR/WU.'
    };
  }
  if (snapshot.snapshot_time || snapshot.observed_temp_c != null || snapshot.forecast_distribution) {
    return {
      status: 'provided',
      snapshot_time: snapshot.snapshot_time ?? null,
      detail: 'Caller-provided weather snapshot; not independently verified by ASP.'
    };
  }
  return {
    status: 'missing',
    snapshot_time: null,
    detail: 'weather object present but no snapshot_time / observed / forecast.'
  };
}

function normalizeForecast(rows) {
  if (!Array.isArray(rows)) return [];
  return rows.map((r) => ({
    bucket: normalizeTempBucket(r.bucket || r.label || r.temp),
    prob: Number.isFinite(Number(r.prob ?? r.probability)) ? round2(Number(r.prob ?? r.probability)) : null
  })).filter((r) => r.bucket);
}

function readObserved(snapshot) {
  if (!snapshot) return null;
  if (snapshot.observed_temp_c != null) {
    return { value: Number(snapshot.observed_temp_c), unit: 'C' };
  }
  if (snapshot.observed_temp_f != null) {
    return { value: Number(snapshot.observed_temp_f), unit: 'F' };
  }
  return null;
}

function compareForecastToMarket(forecast, buckets) {
  if (!forecast.length || !buckets.length) {
    return { status: 'unavailable', note: 'Need forecast_distribution and ladder.' };
  }
  const topF = forecast.slice().sort((a, b) => (b.prob ?? 0) - (a.prob ?? 0))[0];
  const marketRow = buckets.find((b) => b.bucket === topF.bucket);
  return {
    status: marketRow ? 'aligned_bucket_present' : 'forecast_mode_missing_on_ladder',
    forecast_mode_bucket: topF.bucket,
    forecast_mode_prob: topF.prob,
    market_yes_for_mode: marketRow?.yes ?? null
  };
}

function buildThesis({ modal, forecast, observed, yesSum, buckets }) {
  const parts = [];
  if (modal) parts.push(`Market modal bucket ${modal.bucket} (Yes≈${modal.yes}).`);
  if (forecast[0]) {
    const top = forecast.slice().sort((a, b) => (b.prob ?? 0) - (a.prob ?? 0))[0];
    parts.push(`Caller forecast mode ${top.bucket} (p≈${top.prob}).`);
  }
  if (observed) parts.push(`Observed ${observed.value}°${observed.unit} (caller-supplied).`);
  if (yesSum > 1.15 || yesSum < 0.85) parts.push(`Yes-mass sum ${round2(yesSum)} looks off — check overlapping buckets.`);
  if (!buckets.length) parts.push('No temperature buckets parsed from matrix.');
  return parts.join(' ') || 'Insufficient weather ladder structure.';
}

function normalizeTempBucket(text) {
  const s = String(text ?? '').trim();
  if (!s) return 'unknown';
  // Prefer compact degree labels already on Polymarket titles
  const m = s.match(/(-?\d+(?:\.\d+)?)\s*°?\s*[CF]?(?:\s*[-–]\s*(-?\d+(?:\.\d+)?))?/i);
  if (m && m[2]) return `${m[1]}-${m[2]}`;
  if (m) return `${m[1]}`;
  return s.slice(0, 48);
}

function parseTempC(label) {
  const m = String(label).match(/(-?\d+(?:\.\d+)?)/);
  return m ? Number(m[1]) : null;
}

function compareBuckets(a, b) {
  if (a.temp_c != null && b.temp_c != null) return a.temp_c - b.temp_c;
  return String(a.bucket).localeCompare(String(b.bucket));
}

function extractCity(title) {
  const m = String(title ?? '').match(/\b(in|at)\s+([A-Z][A-Za-z\- ]{2,40})\b/);
  return m ? m[2].trim() : null;
}
