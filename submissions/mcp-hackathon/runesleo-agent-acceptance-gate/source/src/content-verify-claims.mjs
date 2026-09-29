// Content Verify Claims (content_verify_claims) — rule-based pre-publish claim check.
// Compares caller-supplied claims against caller-supplied source excerpts.
// Not LLM cross-model review; use leo-route review for full content-verify skill.

const SERVICE_ID = 'content_verify_claims';

const STANDARD_CAVEATS = [
  'Rule-based overlap check only — not multi-model content-verify or web fetch.',
  'Caller must supply source excerpts; URLs alone are not fetched in this endpoint.',
  'Not a substitute for human review before publish.'
];

export function assessContentVerifyClaims(input = {}) {
  const claims = normalizeStringArray(input.claims ?? input.claim);
  const sources = normalizeSources(input.sources ?? input.source);

  if (!claims.length) {
    throw new Error('claims[] is required (one or more strings to verify).');
  }
  if (!sources.length) {
    throw new Error('sources[] is required (text excerpts and/or url labels; text is used for matching).');
  }

  const corpus = buildCorpus(sources);
  const supported = [];
  const unsupported = [];
  const needs_review = [];
  const conflicts = [];

  for (const claim of claims) {
    const result = evaluateClaim(claim, corpus, sources);
    if (result.status === 'supported') supported.push(result);
    else if (result.status === 'unsupported') unsupported.push(result);
    else needs_review.push(result);
  }

  detectNumericConflicts(claims, corpus, conflicts);

  const verdict = verdictFrom(supported, unsupported, needs_review, conflicts);

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      claim_count: claims.length,
      source_count: sources.length
    },
    verdict,
    consensus: buildConsensus(verdict, supported, unsupported, needs_review),
    supported,
    unsupported,
    needs_review,
    conflicts,
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Run_leo-route_review_or_human_check_before_publish',
    source: { method: 'rule_based_text_overlap_and_numeric_match' }
  };
}

export function buildContentVerifyClaimsFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: { claim_count: 0, source_count: 0 },
    verdict: 'needs_review',
    consensus: 'Demo fallback — provide claims[] and sources[] with text excerpts.',
    supported: [],
    unsupported: [],
    needs_review: [],
    conflicts: [],
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Run_leo-route_review_or_human_check_before_publish',
    source: { method: 'static_fallback' }
  };
}

function normalizeStringArray(value) {
  const items = Array.isArray(value) ? value : [value];
  return items.map((item) => String(item).trim()).filter((item) => item.length > 0);
}

function normalizeSources(value) {
  const items = Array.isArray(value) ? value : [value];
  return items.map((item, index) => {
    if (typeof item === 'string') {
      return { id: `source_${index + 1}`, url: null, text: item.trim() };
    }
    if (item && typeof item === 'object') {
      return {
        id: String(item.id ?? `source_${index + 1}`),
        url: item.url ? String(item.url) : null,
        text: String(item.text ?? item.excerpt ?? item.content ?? '').trim()
      };
    }
    return { id: `source_${index + 1}`, url: null, text: '' };
  }).filter((s) => s.text.length > 0 || s.url);
}

function buildCorpus(sources) {
  return sources.map((s) => ({
    id: s.id,
    text: s.text.toLowerCase(),
    numbers: extractNumbers(s.text)
  }));
}

function evaluateClaim(claim, corpus, sources) {
  const claimLower = claim.toLowerCase();
  const claimNumbers = extractNumbers(claim);
  const claimTokens = significantTokens(claimLower);

  let best = { score: 0, source_id: null };
  for (const entry of corpus) {
    if (!entry.text && !entry.numbers.length) continue;
    let score = 0;
    if (claimNumbers.length) {
      const matched = claimNumbers.filter((n) => entry.numbers.includes(n));
      score += matched.length / claimNumbers.length * 0.6;
    }
    const tokenHits = claimTokens.filter((t) => entry.text.includes(t)).length;
    if (claimTokens.length) score += tokenHits / claimTokens.length * 0.4;
    if (score > best.score) best = { score, source_id: entry.id };
  }

  const entry = {
    claim,
    best_source_id: best.source_id,
    match_score: round2(best.score)
  };

  if (claimNumbers.length) {
    const anyNumberMatch = corpus.some((c) =>
      claimNumbers.every((n) => c.numbers.includes(n)));
    if (!anyNumberMatch) {
      return { ...entry, status: 'unsupported', reason: 'Numeric tokens in claim not found in any source excerpt.' };
    }
  }

  if (best.score >= 0.55) {
    return { ...entry, status: 'supported', reason: 'Claim overlaps source text/numbers above threshold.' };
  }
  if (best.score >= 0.25) {
    return { ...entry, status: 'needs_review', reason: 'Partial overlap — manual review recommended.' };
  }
  return { ...entry, status: 'unsupported', reason: 'Insufficient overlap with supplied source excerpts.' };
}

function detectNumericConflicts(claims, corpus, conflicts) {
  const allSourceNumbers = new Set(corpus.flatMap((c) => c.numbers));
  for (const claim of claims) {
    const nums = extractNumbers(claim);
    for (const n of nums) {
      if (allSourceNumbers.size > 0 && !allSourceNumbers.has(n)) {
        conflicts.push({
          type: 'claim_number_not_in_sources',
          value: n,
          claim
        });
      }
    }
  }
}

function verdictFrom(supported, unsupported, needs_review, conflicts) {
  if (conflicts.length && unsupported.length) return 'fail';
  if (unsupported.length && !supported.length) return 'fail';
  if (unsupported.length || needs_review.length || conflicts.length) return 'needs_review';
  return 'pass';
}

function buildConsensus(verdict, supported, unsupported, needs_review = []) {
  if (verdict === 'pass') {
    return `All ${supported.length} claim(s) overlap supplied source excerpts above threshold.`;
  }
  if (verdict === 'fail') {
    return `${unsupported.length} unsupported claim(s); review before publish.`;
  }
  return `Mixed support: ${supported.length} ok, ${unsupported.length} unsupported, ${needs_review.length} need review.`;
}

function extractNumbers(text) {
  const matches = String(text).match(/\d+(?:\.\d+)?%?/g) ?? [];
  return [...new Set(matches.map((m) => m.replace(/%$/, '')))];
}

function significantTokens(text) {
  return [...new Set(
    text.split(/[^a-z0-9\u4e00-\u9fff]+/i)
      .map((t) => t.trim())
      .filter((t) => t.length >= 4)
  )].slice(0, 12);
}

function round2(value) {
  return Math.round(value * 100) / 100;
}
