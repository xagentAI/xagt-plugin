import assert from 'node:assert/strict';
import {
  toCopilotResearchUnit,
  COPILOT_SCHEMA_ID,
  AGENT_EXTENSION_KEY
} from '../src/pm-event-to-copilot-research-unit.mjs';

function baseAgent(overrides = {}) {
  return {
    schema_version: '0.2',
    service_id: 'pm_event_readout',
    mode: 'live',
    generated_at: '2026-07-12T04:00:00.000Z',
    input: {
      market_url: 'https://polymarket.com/event/fed-decision-in-july',
      slug: 'fed-decision-in-july-no-change',
      condition_id: null
    },
    event: 'Fed decision in July',
    event_slug: 'fed-decision-in-july',
    market: 'fed-decision-in-july-no-change',
    market_title: 'No change',
    current_price: { yes: 0.82, no: 0.18 },
    event_time: '2026-07-31T00:00:00Z',
    fixture_status: 'ok',
    category: 'generic',
    category_depth: 'core_only',
    sources_read: ['gamma:market', 'gamma:event'],
    base_case: 'Market prices "No change" at 0.82 (82% implied).',
    market_implied_view: 'Hold is already the base case.',
    what_is_already_priced: ['Hold @ 0.82'],
    what_may_not_be_priced: ['Surprise cut path'],
    event_matrix: [
      { slug: 'fed-decision-in-july-no-change', yes_price: 0.82, liquidity: 12000 },
      { slug: 'fed-decision-in-july-25-bps-decrease', yes_price: 0.15, liquidity: 8000 }
    ],
    matrix_status: 'complete',
    related_market_count: 2,
    missing_market_groups: [],
    tradability: 'high',
    tradability_reasons: [],
    next_decision_card_needed: 'yes',
    hard_gate: 'no_orders_no_account_mutation',
    ...overrides
  };
}

{
  const { ok, value, errors } = toCopilotResearchUnit(baseAgent(), { unitId: 'unit-fed-1' });
  assert.equal(ok, true, errors?.join('; '));
  assert.equal(value.schemaId, COPILOT_SCHEMA_ID);
  assert.equal(value.unitId, 'unit-fed-1');
  assert.equal(value.market.platform, 'polymarket');
  assert.equal(value.market.marketId, 'fed-decision-in-july-no-change');
  assert.equal(value.freshness.status, 'complete');
  assert.equal(value.freshness.asOf, '2026-07-12T04:00:00.000Z');
  assert.equal(value.compliance.analysisAllowed, true);
  assert.equal(value.decision.eligibility, 'OBSERVE');
  assert.notEqual(value.decision.eligibility, 'BET');
  assert.equal(value.decision.edge, null);
  assert.ok(value.summary.en.includes('82%'));
  assert.equal(value.extensions[AGENT_EXTENSION_KEY].service_id, 'pm_event_readout');
  assert.ok(!('weather' in value));
  assert.ok(!('orders' in value));
}

{
  const { ok, value } = toCopilotResearchUnit(
    baseAgent({
      tradability: 'weak',
      matrix_status: 'incomplete',
      tradability_reasons: ['missing_outcome_prices'],
      event_matrix: [{ slug: 'only', yes_price: 0.5 }],
      related_market_count: 1
    }),
    { unitId: 'unit-partial' }
  );
  assert.equal(ok, true);
  assert.equal(value.freshness.status, 'partial');
  assert.ok(value.freshness.partialReasons.includes('missing_outcome_prices'));
  assert.equal(value.decision.eligibility, 'AVOID');
}

{
  const { ok, value } = toCopilotResearchUnit(
    baseAgent({
      current_price: {},
      event_matrix: [],
      matrix_status: 'incomplete',
      tradability: 'weak'
    }),
    { unitId: 'unit-missing' }
  );
  assert.equal(ok, true);
  assert.equal(value.freshness.status, 'missing');
  assert.equal(value.decision, null);
  assert.equal(value.evidence.hasPrices, false);
}

{
  const { ok, value } = toCopilotResearchUnit(
    baseAgent({ tradability: 'low', matrix_status: 'complete' }),
    { unitId: 'unit-low' }
  );
  assert.equal(ok, true);
  assert.equal(value.decision.eligibility, 'AVOID');
}

{
  const { ok, value } = toCopilotResearchUnit(
    baseAgent({ hard_gate: 'blocked_for_test' }),
    { unitId: 'unit-blocked' }
  );
  assert.equal(ok, true);
  assert.equal(value.compliance.analysisAllowed, false);
  assert.equal(value.decision, null);
}

{
  const r = toCopilotResearchUnit(baseAgent(), {});
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => e.includes('unitId')));
}

{
  const r = toCopilotResearchUnit(null, { unitId: 'x' });
  assert.equal(r.ok, false);
}

console.log('pm-event-dual-surface-test: PASS');
