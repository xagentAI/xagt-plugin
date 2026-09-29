// Publish Readiness — combines Content Slop Check + Content Verify Claims into
// one pre-publish gate: ready / edit_first / block.
// Deterministic, no rewrite, no web fetch, no account mutation.

import { assessContentSlopCheck } from './content-slop-check.mjs';
import { assessContentVerifyClaims } from './content-verify-claims.mjs';

const SERVICE_ID = 'publish_readiness';

const STANDARD_CAVEATS = [
  'Combines rule-based slop detection + claim/source overlap — not multi-model review.',
  'Does not publish, schedule, rewrite, or mutate any account.',
  'Caller must supply source excerpts when claims are provided; URLs alone are not fetched.'
];

/**
 * @param {object} input
 * @param {string} [input.text]
 * @param {string} [input.content]
 * @param {string} [input.draft]
 * @param {string[]} [input.claims]
 * @param {Array<{text?: string, url?: string}>} [input.sources]
 * @param {number} [input.max_slop_score] default 55
 */
export function assessPublishReadiness(input = {}) {
  const text = String(input.text ?? input.content ?? input.draft ?? '').trim();
  if (!text) {
    throw new Error('text (draft content) is required');
  }

  const maxSlop = clampInt(input.max_slop_score, 10, 90, 55);
  const claims = normalizeClaims(input.claims ?? input.claim);
  const sources = input.sources ?? input.source;

  const slop = assessContentSlopCheck({ text });

  let verify = null;
  let verify_skipped = false;
  if (claims.length) {
    const sourceList = Array.isArray(sources) ? sources : (sources ? [sources] : []);
    const hasTextSource = sourceList.some((s) => s && String(s.text ?? '').trim());
    if (!hasTextSource) {
      throw new Error('claims[] provided but sources[].text excerpts are missing (URLs alone are not fetched).');
    }
    verify = assessContentVerifyClaims({ claims, sources: sourceList });
  } else {
    verify_skipped = true;
  }

  const blockers = [];
  const edit_reasons = [];

  if (slop.verdict === 'sloppy' || slop.slop_score_0_100 >= maxSlop) {
    blockers.push(`slop_score ${slop.slop_score_0_100} ≥ ${maxSlop} (or verdict=sloppy)`);
  } else if (slop.verdict === 'needs_edit') {
    edit_reasons.push(`slop needs_edit (score ${slop.slop_score_0_100})`);
  }

  if (slop.slop_flags?.some((f) => f.id === 'as_an_ai')) {
    blockers.push('model self-reference (as_an_ai) must be removed');
  }

  if (verify) {
    if (verify.verdict === 'fail' || (verify.unsupported?.length ?? 0) > 0 || (verify.conflicts?.length ?? 0) > 0) {
      blockers.push(`claims verify=${verify.verdict} (unsupported=${verify.unsupported?.length ?? 0}, conflicts=${verify.conflicts?.length ?? 0})`);
    } else if (verify.verdict === 'needs_review') {
      edit_reasons.push('claims need_review before publish');
    }
  } else if (looksLikeFactHeavy(text) && verify_skipped) {
    edit_reasons.push('draft looks fact-heavy but claims[]/sources[] were omitted');
  }

  let action = 'ready';
  if (blockers.length) action = 'block';
  else if (edit_reasons.length) action = 'edit_first';

  const buyer_summary_zh = buildBuyerSummaryZh(action, slop, verify, blockers, edit_reasons);

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at: new Date().toISOString(),
    input: {
      text_chars: text.length,
      claim_count: claims.length,
      verify_skipped,
      max_slop_score: maxSlop
    },
    action,
    buyer_summary_zh,
    value_loop: {
      why_pay_again: 'Each draft is different; re-run before every publish attempt.',
      stale_after_minutes: null,
      best_used_in: 'content_publish_gate_before_post',
      paid_value_tier: 'A_repeat_workflow',
      fulfillment: 'edge_on_demand_no_llm'
    },
    blockers,
    edit_reasons,
    slop: {
      verdict: slop.verdict,
      slop_score_0_100: slop.slop_score_0_100,
      slop_flags: slop.slop_flags,
      suggested_actions: slop.suggested_actions
    },
    verify: verify
      ? {
          verdict: verify.verdict,
          consensus: verify.consensus,
          supported_count: verify.supported?.length ?? 0,
          unsupported_count: verify.unsupported?.length ?? 0,
          needs_review_count: verify.needs_review?.length ?? 0,
          conflicts_count: verify.conflicts?.length ?? 0
        }
      : null,
    caveats: [...STANDARD_CAVEATS],
    next_gate: action === 'ready'
      ? 'Human_spot_check_then_publish'
      : 'Fix_blockers_or_edit_reasons_then_rerun',
    source: {
      method: 'compose_content_slop_check_plus_content_verify_claims',
      oss_lineage: 'talk-human / content-verify rules productized'
    }
  };
}

export function buildPublishReadinessFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    input: { text_chars: 0, claim_count: 0, verify_skipped: true, max_slop_score: 55 },
    action: 'edit_first',
    buyer_summary_zh: '演示回退：请提供 text（及可选 claims/sources）后再跑发布就绪闸门。',
    blockers: [],
    edit_reasons: ['demo_fallback'],
    slop: null,
    verify: null,
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    next_gate: 'Fix_blockers_or_edit_reasons_then_rerun',
    source: { method: 'static_fallback' }
  };
}

function buildBuyerSummaryZh(action, slop, verify, blockers, edit_reasons) {
  const slopBit = `注水分 ${slop.slop_score_0_100}（${slop.verdict}）`;
  const verifyBit = verify
    ? `断言核查 ${verify.verdict}（支持${verify.supported?.length ?? 0}/不支持${verify.unsupported?.length ?? 0}）`
    : '未提供 claims，跳过断言核查';
  if (action === 'ready') {
    return `可发布（仍建议人工扫一眼）。${slopBit}；${verifyBit}。`;
  }
  if (action === 'block') {
    return `先别发：${blockers.join('；')}。${slopBit}；${verifyBit}。`;
  }
  return `先改再发：${edit_reasons.join('；')}。${slopBit}；${verifyBit}。`;
}

function looksLikeFactHeavy(text) {
  const nums = (text.match(/\d+(?:\.\d+)?%?|\b(?:USDT|USD|\$)\s?\d+/gi) || []).length;
  return nums >= 2 || /根据|数据显示|官方|销量|成交/.test(text);
}

function normalizeClaims(value) {
  if (value == null) return [];
  const items = Array.isArray(value) ? value : [value];
  return items.map((c) => String(c).trim()).filter(Boolean);
}

function clampInt(value, min, max, fallback) {
  const n = Number.parseInt(value, 10);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}
