// PM Wallet Report — one-pager composing toolkit profile + brier + pnl quick audit.
// Lineage: polymarket-toolkit Drawer A (research an address). Read-only.

import { assessPmProfileLive, buildPmProfileFallback } from './pm-profile.mjs';
import { assessPmBrierLive, buildPmBrierFallback } from './pm-brier.mjs';
import { assessPmPnlAuditLive, buildPmPnlAuditFallback } from './pm-pnl-audit.mjs';

const SERVICE_ID = 'pm_wallet_report';

const STANDARD_CAVEATS = [
  'Composed read-only report from polymarket-toolkit surfaces (profile + brier + pnl quick).',
  'Quick PnL is not full cashflow replay — call /pm-pnl-audit mode=full when needed.',
  'No wallet custody, no orders.'
];

/**
 * @param {object} input
 * @param {string} [input.address]
 * @param {string} [input.username]
 * @param {'quick'|'full'} [input.pnl_mode='quick']
 */
export async function assessPmWalletReportLive(input = {}, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch;
  const raw = String(input.address ?? input.wallet ?? input.username ?? input.query ?? '').trim();
  if (!raw) throw new Error('pm-wallet-report requires address or username.');

  const pnlMode = String(input.pnl_mode ?? input.mode ?? 'quick').toLowerCase() === 'full' ? 'full' : 'quick';

  const [profileR, brierR, pnlR] = await Promise.allSettled([
    assessPmProfileLive(input, { fetchImpl }),
    assessPmBrierLive(input, { fetchImpl }),
    assessPmPnlAuditLive({ ...input, mode: pnlMode }, { fetchImpl })
  ]);

  const profile = profileR.status === 'fulfilled' ? profileR.value : null;
  const brier = brierR.status === 'fulfilled' ? brierR.value : null;
  const pnl = pnlR.status === 'fulfilled' ? pnlR.value : null;

  if (!profile && !brier && !pnl) {
    throw new Error('All wallet report layers failed upstream');
  }

  const address = profile?.input?.address || pnl?.input?.address || null;
  const action = chooseCompositeAction(pnl, brier);
  const generated_at = new Date().toISOString();
  const evidenceState = buildEvidenceState({ profile, brier, pnl });

  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'live',
    generated_at,
    input: {
      query: raw,
      address,
      pnl_mode: pnlMode
    },
    layers: {
      profile: profile
        ? {
            pnl_7d: profile.profile?.pnl_7d_usdt ?? profile.pnl_7d ?? profile.leaderboard_pnl_7d ?? null,
            open_positions: profile.profile?.open_positions_sampled ?? profile.open_positions ?? profile.positions_sampled ?? null,
            buyer_summary_zh: profile.buyer_summary_zh
          }
        : { error: profileR.reason?.message || 'unavailable' },
      brier: brier
        ? {
            brier: brier.brier ?? brier.score ?? null,
            rating: brier.rating ?? null,
            settled_sample: brier.settled_markets ?? brier.settled_count ?? brier.sample_size ?? null,
            buyer_summary_zh: brier.buyer_summary_zh
          }
        : { error: brierR.reason?.message || 'unavailable' },
      pnl_audit: pnl
        ? {
            mode: pnl.mode,
            divergence_verdict: pnl.divergence_verdict,
            action: pnl.action,
            leaderboard_profit: pnl.leaderboard_profit?.amount_usd ?? null,
            cashflow_complete: pnl.cashflow_replay?.complete ?? null,
            buyer_summary_zh: pnl.buyer_summary_zh
          }
        : { error: pnlR.reason?.message || 'unavailable' }
    },
    composite_action: action,
    evidence_state: evidenceState,
    consumer_contract: buildConsumerContract({ action, evidenceState, pnlMode }),
    buyer_summary_zh: buildZh({ address, profile, brier, pnl, action }),
    buyer_summary_en: buildEn({ address, profile, brier, pnl, action }),
    value_loop: {
      why_pay_again: 'Wallet positions, LB PnL and calibration move; re-run before copying.',
      stale_after_minutes: 15,
      paid_value_tier: 'toolkit_wallet_report',
      oss_lineage: 'polymarket-toolkit Drawer A: profile + brier + pnl',
      llm_api_key_required: false
    },
    caveats: STANDARD_CAVEATS,
    next_gate: action === 'distrust_claims'
      ? 'Do_not_copy_without_full_pnl_replay'
      : 'Optional_pm_pnl_audit_mode_full',
    source: {
      provider: 'polymarket_public_api',
      composed: ['pm_profile', 'pm_brier', 'pm_pnl_audit']
    }
  };
}

export function buildPmWalletReportFallback(input = {}) {
  return {
    schema_version: '0.1',
    service_id: SERVICE_ID,
    mode: 'public_safe_demo',
    generated_at: new Date().toISOString(),
    layers: {
      profile: buildPmProfileFallback(input),
      brier: buildPmBrierFallback(input),
      pnl_audit: buildPmPnlAuditFallback(input)
    },
    composite_action: 'verify_manually',
    buyer_summary_zh: '钱包一页纸回退：上游不可用。',
    caveats: [...STANDARD_CAVEATS, 'Demo fallback.'],
    source: { provider: 'static_fallback' }
  };
}

function buildEvidenceState({ profile, brier, pnl }) {
  const available_layers = [];
  if (profile) available_layers.push('profile');
  if (brier) available_layers.push('brier');
  if (pnl) available_layers.push('pnl_audit');
  const all = ['profile', 'brier', 'pnl_audit'];
  const missing_layers = all.filter((name) => !available_layers.includes(name));
  const status = missing_layers.length === 0 ? 'live' : (available_layers.length > 0 ? 'degraded' : 'insufficient_evidence');
  return { status, available_layers, missing_layers, sufficient_for_action: status === 'live' && Boolean(pnl) };
}

function buildConsumerContract({ action, evidenceState, pnlMode }) {
  const degraded = evidenceState.status !== 'live';
  return {
    schema_version: '0.1',
    decision: degraded ? 'do_not_autocopy' : action,
    can_autocopy: !degraded && action === 'trust_for_copy' && pnlMode === 'full',
    requires_human_review: degraded || action !== 'trust_for_copy',
    readback_key: 'generated_at',
    stale_after_minutes: 15,
    follow_up: degraded ? 'retry_same_report_before_acting' : (action === 'distrust_claims' ? 'run_pm_pnl_audit_full_before_copying' : (pnlMode === 'quick' ? 'optional_pm_pnl_audit_full' : 'none')),
    fail_closed_reason: degraded ? 'missing_layers:' + evidenceState.missing_layers.join(',') : null
  };
}

function chooseCompositeAction(pnl, brier) {
  if (pnl?.action === 'distrust_claims') return 'distrust_claims';
  // Only full cashflow trust_for_copy may lift composite; quick_triage_ok stays manual.
  if (pnl?.action === 'trust_for_copy' && brier?.rating === 'good') return 'trust_for_copy';
  if (pnl?.action === 'trust_for_copy') return 'trust_with_calibration_check';
  if (pnl?.action === 'quick_triage_ok') return 'verify_manually';
  return 'verify_manually';
}

function buildZh({ address, profile, brier, pnl, action }) {
  const who = shorten(address);
  const lb = pnl?.leaderboard_profit?.amount_usd
    ?? profile?.profile?.pnl_7d_usdt
    ?? profile?.pnl_7d?.amount
    ?? 'n/a';
  const rating = brier?.rating ?? 'n/a';
  const verdict = pnl?.divergence_verdict ?? 'n/a';
  return `钱包一页纸 ${who}：PnL层 verdict=${verdict}；Brier=${rating}；LB≈${lb}；composite=${action}。来自 toolkit 组合，非跟单建议。`;
}

function buildEn({ address, profile, brier, pnl, action }) {
  const who = shorten(address);
  const rating = brier?.rating ?? 'n/a';
  const verdict = pnl?.divergence_verdict ?? 'n/a';
  return `Wallet report ${who}: pnl verdict=${verdict}; brier=${rating}; composite=${action}. Toolkit compose; not copy advice.`;
}

function shorten(address) {
  const value = String(address ?? '');
  if (!value.startsWith('0x') || value.length < 12) return value || 'wallet';
  return `${value.slice(0, 6)}...${value.slice(-4)}`;
}
