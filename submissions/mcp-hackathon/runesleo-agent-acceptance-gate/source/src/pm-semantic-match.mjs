// Lightweight semantic entity matching for scenario discovery.
// Keeps discovery honest for queries like "Lakers" without broadening SKU count.

const STOP_WORDS = new Set([
  'a', 'an', 'and', 'are', 'at', 'be', 'by', 'for', 'from', 'in', 'is', 'of',
  'on', 'or', 'the', 'to', 'vs', 'v', 'will', 'win', 'winner', 'market',
  'match', 'game', 'event', 'readout', 'card', 'who', 'what', 'when'
]);

const GENERIC_CATEGORY_TERMS = new Set([
  'nba', 'basketball', 'wnba',
  'football', 'soccer', 'epl', 'ucl', 'premier', 'league', 'champions',
  'tennis', 'atp', 'wta',
  'fed', 'fomc', 'federal', 'reserve', 'interest', 'rates', 'rate', 'cut', 'hike',
  'politics', 'political', 'election', 'president', 'senate', 'governor',
  'weather', 'temperature', 'temp'
]);

const ENTITY_ALIASES = [
  ['lakers', 'la lakers', 'los angeles lakers', 'lal'],
  ['clippers', 'la clippers', 'los angeles clippers', 'lac'],
  ['lebron', 'lebron james'],
  ['celtics', 'boston celtics'],
  ['knicks', 'new york knicks', 'ny knicks', 'nyk'],
  ['warriors', 'golden state warriors', 'gsw'],
  ['arsenal'],
  ['man city', 'manchester city'],
  ['man united', 'man utd', 'manchester united'],
  ['chelsea'],
  ['liverpool'],
  ['nyc', 'new york', 'new york city'],
  ['fomc', 'fed', 'federal reserve']
];

const ALIAS_GROUPS = ENTITY_ALIASES.map((aliases, index) => ({
  id: `alias_${index}`,
  aliases,
  tokens: unique(aliases.flatMap(simpleTokens))
}));

export function extractSemanticTokens(text) {
  const baseTokens = simpleTokens(text).filter((token) => !STOP_WORDS.has(token));
  const out = new Set(baseTokens);
  const normalized = normalize(text);
  for (const group of ALIAS_GROUPS) {
    if (group.aliases.some((alias) => containsPhrase(normalized, alias))) {
      for (const token of group.tokens) out.add(token);
      out.add(group.id);
    }
  }
  return [...out].filter((token) => token.length > 1);
}

export function queryRequiresEntityMatch(query) {
  const raw = String(query ?? '').trim();
  if (!raw) return false;
  const normalized = normalize(raw);
  const tokens = simpleTokens(raw).filter((token) => !STOP_WORDS.has(token));
  if (!tokens.length) return false;

  const hasAlias = ALIAS_GROUPS.some((group) => (
    // Treat bare Fed/FOMC as category-generic even though it is an alias group.
    group.aliases.some((alias) => containsPhrase(normalized, alias))
    && !group.aliases.every((alias) => ['fed', 'fomc', 'federal reserve'].includes(alias))
  ));
  if (hasAlias) return true;

  const nonGeneric = tokens.filter((token) => !GENERIC_CATEGORY_TERMS.has(token));
  if (!nonGeneric.length) return false;

  // Avoid treating arbitrary fallback phrases as entities. Multi-token titlecase
  // inputs often are specific names ("Los Angeles", "Candidate A").
  const titlecaseWords = raw.match(/\b[A-Z][a-z]+(?:\b|$)/g) || [];
  return titlecaseWords.length >= 2;
}

export function scoreSemanticMatch({ query, title, slug, eventTitle } = {}) {
  const queryTokens = extractSemanticTokens(query);
  if (!queryTokens.length) return 0;
  const candidateText = [title, slug, eventTitle].filter(Boolean).join(' ');
  const candidateTokens = new Set(extractSemanticTokens(candidateText));
  if (!candidateTokens.size) return 0;

  let overlap = 0;
  let aliasOverlap = 0;
  for (const token of queryTokens) {
    if (!candidateTokens.has(token)) continue;
    overlap += 1;
    if (token.startsWith('alias_')) aliasOverlap += 1;
  }

  const meaningfulQuery = queryTokens.filter((token) => !GENERIC_CATEGORY_TERMS.has(token));
  const denominator = Math.max(1, meaningfulQuery.length || queryTokens.length);
  const coverage = Math.min(1, overlap / denominator);
  const exactPhraseBonus = hasExactAliasPhrase(query, candidateText) ? 2 : 0;
  const aliasBonus = aliasOverlap > 0 ? 3 : 0;

  return round2(Math.min(10, coverage * 6 + aliasBonus + exactPhraseBonus));
}

function hasExactAliasPhrase(query, candidateText) {
  const q = normalize(query);
  const c = normalize(candidateText);
  for (const group of ALIAS_GROUPS) {
    const qHit = group.aliases.some((alias) => containsPhrase(q, alias));
    if (!qHit) continue;
    if (group.aliases.some((alias) => containsPhrase(c, alias))) return true;
  }
  return false;
}

function containsPhrase(normalizedText, phrase) {
  const normalizedPhrase = normalize(phrase);
  return new RegExp(`(?:^|\\s)${escapeRegExp(normalizedPhrase)}(?:\\s|$)`).test(normalizedText);
}

function simpleTokens(text) {
  return normalize(text)
    .split(/\s+/)
    .map((token) => token.trim())
    .filter(Boolean);
}

function normalize(text) {
  return String(text ?? '')
    .toLowerCase()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/&/g, ' and ')
    .replace(/[^a-z0-9]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function unique(values) {
  return [...new Set(values)];
}

function round2(value) {
  return Math.round(value * 100) / 100;
}

function escapeRegExp(value) {
  return String(value).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
