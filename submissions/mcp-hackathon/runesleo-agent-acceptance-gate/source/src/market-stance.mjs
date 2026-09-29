// Shared asset-stance classifier for Polymarket crypto event markets.
//
// Extracted 2026-07-30 from duplicated copies in crypto-market-regime.mjs and
// event-price-divergence.mjs, which had drifted into the same defect.
//
// Measured against 362 live Gamma markets (bitcoin/ethereum/solana, active only,
// 2026-07-30): the old rule ended with `|| /\$\s?\d/ → +1`, i.e. any Yes-market
// question carrying a dollar figure that missed the bearish keyword list was
// called bullish. 66 of the 362 markets fell through to that branch and every one
// was scored +1, but only ~6 deserved it:
//
//   "Will the price of Ethereum be less than $1,400 on July 30?"        → scored +1, is bearish
//   "Will the price of Ethereum be between $1,400 and $1,500 …?" (×54)  → scored +1, has NO direction
//   "Will the price of Ethereum be greater than $2,300 …?"              → scored +1, correct
//
// A range bucket cannot be signed without knowing where spot sits relative to the
// bucket, so it must be skipped rather than guessed. Because the bucket markets are
// numerous and carry volume, the old fallback pushed a volume-weighted bullish drift
// into the regime score (Polymarket sentiment carries 25% weight) — a systematic
// long bias, not a rounding error.
//
// Rule order now: explicit Up/Down outcome → range bucket (skip) → bearish compare →
// bullish compare → keyword polarity → unknown (0). Fail closed: when the phrasing is
// not recognised the market is skipped, never assumed bullish.

/** Range buckets: "between $A and $B", "$A to $B", "$A–$B". No direction. */
const RANGE_BUCKET = /\bbetween\b[^?]*\band\b|\$\s?[\d,.]+\s*(?:–|—|-|to)\s*\$\s?[\d,.]+/;

/** Explicit downside comparisons, including the ones the old list missed. */
const BEARISH_COMPARE =
  /\b(?:less than|lower than|below|under|beneath|at or below|no more than|worth less)\b|\bsub[- ]?\$?\d/;

/** Explicit upside comparisons. */
const BULLISH_COMPARE =
  /\b(?:greater than|more than|higher than|above|over|at or above|at least)\b/;

const BEARISH_KEYWORD = /\b(?:dip|drop|fall|crash|down|decline|plunge|tumble)\b/;
const BULLISH_KEYWORD = /\b(?:reach|hit|up|exceed|surpass|all[- ]time high|ath|rally|moon)\b/;

/**
 * +1 when the first outcome rising is bullish for the asset, -1 when bearish,
 * 0 when the market cannot be interpreted safely (skip it, do not guess).
 *
 * @param {{ primary_outcome: string, title: string }} market
 * @returns {-1|0|1}
 */
export function classifyAssetStance(market) {
  const outcome = String(market?.primary_outcome ?? '').trim().toLowerCase();
  if (outcome === 'up') return 1;
  if (outcome === 'down') return -1;
  if (outcome !== 'yes') return 0;

  const question = String(market?.title ?? '').toLowerCase();
  if (!question) return 0;

  // Buckets first: "between $1,400 and $1,500" also contains no comparison word,
  // but it would otherwise reach the dollar-amount branch and be called bullish.
  if (RANGE_BUCKET.test(question)) return 0;

  if (BEARISH_COMPARE.test(question)) return -1;
  if (BULLISH_COMPARE.test(question)) return 1;
  if (BEARISH_KEYWORD.test(question)) return -1;
  if (BULLISH_KEYWORD.test(question)) return 1;

  // Deliberately no dollar-amount fallback — see header note.
  return 0;
}
