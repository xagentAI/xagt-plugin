// Shared Polymarket Gamma market fetch helpers for PM services.

export const GAMMA_BASE = 'https://gamma-api.polymarket.com';
export const FETCH_TIMEOUT_MS = 8000;

export function resolveMarketRef(input) {
  const conditionId = String(input.condition_id ?? '').trim();
  const slug = String(input.slug ?? '').trim();
  const fromUrl = extractFromMarketUrl(input.market_url);
  return {
    condition_id: conditionId || fromUrl.condition_id || null,
    slug: slug || fromUrl.slug || null
  };
}

export function extractFromMarketUrl(marketUrl) {
  const raw = String(marketUrl ?? '').trim();
  if (!raw) return { slug: null, condition_id: null };

  const conditionMatch = raw.match(/\b(0x[a-fA-F0-9]{64})\b/);
  if (conditionMatch) {
    return { slug: null, condition_id: conditionMatch[1] };
  }

  try {
    const url = new URL(raw);
    const parts = url.pathname.split('/').filter(Boolean);
    const idx = parts.findIndex((part) => part === 'event' || part === 'market');
    if (idx >= 0 && parts[idx + 1]) {
      return { slug: decodeURIComponent(parts[idx + 1]), condition_id: null };
    }
  } catch {
    if (/^[a-z0-9-]+$/i.test(raw)) {
      return { slug: raw, condition_id: null };
    }
  }

  return { slug: null, condition_id: null };
}

export async function fetchMarket(fetchImpl, ref) {
  if (ref.condition_id) {
    const rows = await fetchJson(
      fetchImpl,
      `${GAMMA_BASE}/markets?condition_ids=${encodeURIComponent(ref.condition_id)}`
    );
    const market = pickMarketRow(rows);
    if (market) return normalizeGammaMarket(market);
  }

  if (ref.slug) {
    const rows = await fetchJson(
      fetchImpl,
      `${GAMMA_BASE}/markets?slug=${encodeURIComponent(ref.slug)}`
    );
    const market = pickMarketRow(rows);
    if (market) return normalizeGammaMarket(market);
  }

  return null;
}

function pickMarketRow(rows) {
  const list = Array.isArray(rows) ? rows : [];
  return list.find((row) => row?.conditionId) ?? null;
}

export function normalizeGammaMarket(market) {
  const outcomes = parseJsonArray(market.outcomes);
  const outcome_prices = parseJsonArray(market.outcomePrices).map((value) => Number(value));
  const bestBid = toNumber(market.bestBid);
  const bestAsk = toNumber(market.bestAsk);
  const spread = bestAsk > 0 && bestBid > 0 ? Math.max(0, bestAsk - bestBid) : null;
  const oneDay = Number(market.oneDayPriceChange);
  const events = Array.isArray(market.events)
    ? market.events.map((event) => ({
        id: event?.id ?? null,
        slug: event?.slug ?? event?.ticker ?? null,
        title: event?.title ?? null,
        description: event?.description ?? null
      }))
    : [];

  return {
    condition_id: market.conditionId,
    slug: market.slug ?? market.conditionId,
    title: market.question ?? market.slug ?? market.conditionId,
    description: market.description ?? null,
    group_item_title: market.groupItemTitle ?? null,
    sports_market_type: market.sportsMarketType ?? null,
    events,
    active: market.active !== false,
    closed: Boolean(market.closed),
    volume_24hr: toNumber(market.volume24hr ?? market.volumeNum ?? market.volume),
    volume_total: toNumber(market.volumeNum ?? market.volume),
    outcomes,
    outcome_prices,
    best_bid: bestBid || null,
    best_ask: bestAsk || null,
    spread,
    end_date: market.endDate ?? market.endDateIso ?? null,
    start_time: market.eventStartTime ?? market.startDate ?? market.startDateIso ?? null,
    one_day_price_change: Number.isFinite(oneDay) ? oneDay : null,
    updated_at: market.updatedAt ?? null
  };
}

/** Parent event slug from a normalized market (Gamma embeds events[] on market rows). */
export function eventSlugFromMarket(market) {
  const slug = market?.events?.[0]?.slug;
  return typeof slug === 'string' && slug.trim() ? slug.trim() : null;
}

/** Fetch a Gamma event by slug; returns { slug, title, markets[] } or null. */
export async function fetchEventBySlug(fetchImpl, eventSlug) {
  if (!eventSlug) return null;
  const rows = await fetchJson(
    fetchImpl,
    `${GAMMA_BASE}/events?slug=${encodeURIComponent(eventSlug)}`
  );
  const list = Array.isArray(rows) ? rows : [];
  const event = list.find((row) => row?.slug === eventSlug) ?? list[0] ?? null;
  return normalizeEventRow(event, eventSlug);
}

/**
 * Fetch child events under a Gamma parent_event_id.
 * Same discovery path as pm-manual-trading-lab event_market_matrix_monitor.py
 * (snake_case parent_event_id — camelCase silently returns unrelated events).
 */
export async function fetchChildEventsByParentId(fetchImpl, parentEventId, limit = 100) {
  if (parentEventId == null || parentEventId === '') return [];
  const rows = await fetchJson(
    fetchImpl,
    `${GAMMA_BASE}/events?parent_event_id=${encodeURIComponent(parentEventId)}&limit=${limit}`
  );
  return Array.isArray(rows) ? rows : [];
}

function normalizeEventRow(event, eventSlugFallback = null) {
  if (!event) return null;
  const markets = (Array.isArray(event.markets) ? event.markets : [])
    .map((row) => normalizeGammaMarket(row))
    .filter((market) => market.condition_id);
  return {
    id: event.id ?? null,
    slug: event.slug ?? eventSlugFallback,
    title: event.title ?? event.slug ?? eventSlugFallback,
    description: event.description ?? null,
    start_time: event.startTime ?? event.startDate ?? null,
    end_date: event.endDate ?? null,
    parent_event_id: event.parentEventId ?? event.parent_event_id ?? null,
    markets
  };
}

/**
 * Football/tennis Polymarket splits one match across parent + child events.
 * Prefer Gamma parent_event_id children (skill-aligned). Fall back to known
 * sibling slug heuristics when parent id is missing.
 */
export async function fetchEventBundleWithSiblings(fetchImpl, primaryEventSlug) {
  let primary = await fetchEventBySlug(fetchImpl, primaryEventSlug);
  if (!primary) return null;

  // If caller hit a child event (more-markets / halftime / …), climb to parent
  // so sibling discovery matches the local matrix monitor.
  if (primary.parent_event_id != null) {
    try {
      const parentRows = await fetchJson(
        fetchImpl,
        `${GAMMA_BASE}/events?id=${encodeURIComponent(primary.parent_event_id)}`
      );
      const parentList = Array.isArray(parentRows) ? parentRows : [];
      const parentRaw = parentList[0] ?? null;
      const parent = normalizeEventRow(parentRaw);
      if (parent?.markets?.length) {
        primary = {
          ...parent,
          // keep the caller's slug as entrypoint evidence
          entry_event_slug: primary.slug
        };
      }
    } catch {
      // stay on child primary
    }
  }

  const siblingBundles = [];
  const seenSlugs = new Set([primary.slug].filter(Boolean));

  if (primary.id != null) {
    try {
      const children = await fetchChildEventsByParentId(fetchImpl, primary.id);
      for (const child of children) {
        const bundle = normalizeEventRow(child);
        if (!bundle?.slug || seenSlugs.has(bundle.slug) || !bundle.markets?.length) continue;
        seenSlugs.add(bundle.slug);
        siblingBundles.push(bundle);
      }
    } catch {
      // parent_event_id path optional; fall through to heuristics
    }
  }

  if (!siblingBundles.length) {
    const base = String(primaryEventSlug)
      .replace(/-more-markets$/, '')
      .replace(/-halftime-result$/, '')
      .replace(/-second-half-result$/, '')
      .replace(/-exact-score$/, '')
      .replace(/-player-props$/, '')
      .replace(/-total-corners$/, '')
      .replace(/-first-to-score$/, '');
    const heuristicSlugs = [
      `${base}-more-markets`,
      `${base}-team-to-advance`,
      `${base}-exact-score`,
      `${base}-halftime-result`,
      `${base}-second-half-result`,
      `${base}-first-to-score`,
      `${base}-total-corners`,
      `${base}-player-props`
    ].filter((slug) => slug !== primaryEventSlug && !seenSlugs.has(slug));

    for (const slug of heuristicSlugs) {
      try {
        const bundle = await fetchEventBySlug(fetchImpl, slug);
        if (bundle?.markets?.length) {
          seenSlugs.add(bundle.slug);
          siblingBundles.push(bundle);
        }
      } catch {
        // sibling optional
      }
    }
  }

  const byCondition = new Map();
  for (const market of primary.markets) {
    byCondition.set(market.condition_id, market);
  }
  for (const bundle of siblingBundles) {
    for (const market of bundle.markets) {
      if (!byCondition.has(market.condition_id)) {
        byCondition.set(market.condition_id, market);
      }
    }
  }

  return {
    ...primary,
    markets: [...byCondition.values()],
    sibling_event_slugs: siblingBundles.map((b) => b.slug),
    linked_event_count: 1 + siblingBundles.length,
    discovery: siblingBundles.length && primary.id != null
      ? 'parent_event_id'
      : (siblingBundles.length ? 'heuristic_slugs' : 'primary_only'),
    primary_event_slug: primary.slug
  };
}

export function parseJsonArray(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export async function fetchJson(fetchImpl, url) {
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

export function toNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

export function round2(value) {
  return Math.round(value * 100) / 100;
}

export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
