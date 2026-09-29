// Content Slop Check — rule-based AI-filler / spam-pattern detector for draft text.
// No rewrite, no publish, no LLM. Public ASP surface only.

const SERVICE_ID = 'content_slop_check';

const STANDARD_CAVEATS = [
  'Rule-based slop heuristics only — not a style rewrite and not multi-model review.',
  'Does not publish, schedule, or mutate any account.',
  'High score means more filler risk; human judgment still required.'
];

const SLOP_PATTERNS = [
  { id: 'delve', re: /\bdelve\b/i, weight: 8, note: 'Classic LLM filler verb.' },
  { id: 'landscape', re: /\b(?:in today'?s|the) (?:digital |ever-evolving )?landscape\b/i, weight: 10, note: 'Generic landscape opener.' },
  { id: 'tapestry', re: /\btapestry\b/i, weight: 8, note: 'Ornate filler noun.' },
  { id: 'crucial', re: /\bit(?:'s| is) crucial (?:to|that)\b/i, weight: 6, note: 'Empty emphasis.' },
  { id: 'underscore', re: /\bunderscores? the (?:importance|need|fact)\b/i, weight: 7, note: 'LLM emphasis cliché.' },
  { id: 'not_only', re: /\bnot only\b[\s\S]{0,40}\bbut also\b/i, weight: 5, note: 'Boilerplate contrast.' },
  { id: 'in_conclusion', re: /\b(?:in conclusion|to summarize|in summary)\b/i, weight: 5, note: 'Essay-closing filler.' },
  { id: 'as_an_ai', re: /\bas an ai\b/i, weight: 20, note: 'Model self-reference leak.' },
  { id: 'excited_to', re: /\bi(?:'m| am) (?:excited|thrilled|delighted) to\b/i, weight: 6, note: 'Corporate enthusiasm spam.' },
  { id: 'game_changer', re: /\bgame[- ]changer\b/i, weight: 6, note: 'Hype filler.' },
  { id: 'leverage_synergy', re: /\b(?:leverage|synergy|holistic|robust)\b/i, weight: 4, note: 'Biz jargon density.' },
  { id: 'emoji_spam', re: /(?:[\u{1F300}-\u{1FAFF}].*){4,}/u, weight: 8, note: 'Heavy emoji spam.' },
  { id: 'cn_ai_filler', re: /综上所述|赋能|闭环|抓手|打通|底层逻辑|认知升级/u, weight: 7, note: '中文空话/黑话。' }
];

/**
 * @param {object} input
 * @param {string} [input.text]
 * @param {string} [input.content]
 * @param {string} [input.draft]
 */
export function assessContentSlopCheck(input = {}) {
  const text = String(input.text ?? input.content ?? input.draft ?? '').trim();
  if (!text) {
    throw new Error('text (draft content) is required');
  }

  const flags = [];
  let rawScore = 0;
  for (const pattern of SLOP_PATTERNS) {
    if (pattern.re.test(text)) {
      rawScore += pattern.weight;
      flags.push({ id: pattern.id, weight: pattern.weight, note: pattern.note });
    }
  }

  const words = text.split(/\s+/).filter(Boolean).length;
  const sentences = text.split(/[.!?。！？]+/).filter((s) => s.trim().length > 0).length || 1;
  const avgSentenceLen = words / sentences;
  if (avgSentenceLen > 38) {
    rawScore += 6;
    flags.push({ id: 'long_sentences', weight: 6, note: `Avg sentence ~${Math.round(avgSentenceLen)} words — dense/LLM-ish.` });
  }
  if (words > 0) {
    const unique = new Set(text.toLowerCase().split(/\s+/).filter(Boolean));
    const diversity = unique.size / words;
    if (diversity < 0.45 && words >= 40) {
      rawScore += 8;
      flags.push({ id: 'low_lexical_diversity', weight: 8, note: `Lexical diversity ${diversity.toFixed(2)} looks repetitive.` });
    }
  }

  const slop_score_0_100 = clamp(Math.round(rawScore * 1.4), 0, 100);
  const verdict = slop_score_0_100 >= 55
    ? 'sloppy'
    : slop_score_0_100 >= 30
      ? 'needs_edit'
      : 'clean_enough';

  const suggested_actions = [];
  if (verdict !== 'clean_enough') {
    suggested_actions.push('Cut cliché openers and empty emphasis.');
    suggested_actions.push('Replace abstract claims with concrete numbers or named sources.');
  }
  if (flags.some((f) => f.id === 'as_an_ai')) {
    suggested_actions.push('Remove model self-reference before any public post.');
  }
  if (flags.some((f) => f.id === 'cn_ai_filler')) {
    suggested_actions.push('删掉空话黑话，改成可核验事实句。');
  }

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      char_count: text.length,
      word_count: words,
      sentence_count: sentences
    },
    verdict,
    slop_score_0_100,
    slop_flags: flags,
    readability: {
      avg_sentence_words: Math.round(avgSentenceLen * 10) / 10
    },
    suggested_actions,
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Human_edit_then_content_verify_claims_before_publish',
    source: { method: 'rule_based_slop_heuristics' }
  };
}

export function buildContentSlopCheckFallback() {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: { char_count: 0, word_count: 0, sentence_count: 0 },
    verdict: 'needs_edit',
    slop_score_0_100: 40,
    slop_flags: [{ id: 'demo', weight: 0, note: 'Provide text to score.' }],
    readability: { avg_sentence_words: 0 },
    suggested_actions: ['Pass draft text in JSON field text.'],
    caveats: [...STANDARD_CAVEATS],
    next_gate: 'Human_edit_then_content_verify_claims_before_publish',
    source: { method: 'static_fallback' }
  };
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}
