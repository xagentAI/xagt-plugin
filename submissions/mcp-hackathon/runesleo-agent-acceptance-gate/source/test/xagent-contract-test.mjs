import assert from 'node:assert/strict';
import worker from '../worker/index.mjs';

const COMMIT = '0123456789abcdef0123456789abcdef01234567';
const SLUG = 'runesleo-agent-acceptance-gate';
const ORIGIN = 'https://api.leolabs.me';
const env = {
  XAGENT_GIT_COMMIT: COMMIT,
  XAGENT_PROJECT_SLUG: SLUG
};

{
  const res = await worker.fetch(new Request(`${ORIGIN}/health`), env);
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.status, 'ok');
  assert.equal(body.commit, COMMIT);
}

{
  const res = await worker.fetch(
    new Request(`${ORIGIN}/.well-known/xagent-verification.json`),
    env
  );
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), {
    schemaVersion: 1,
    slug: SLUG,
    commit: COMMIT
  });
}

{
  const res = await worker.fetch(new Request(`${ORIGIN}/health`), {});
  assert.equal(res.status, 503);
  const body = await res.json();
  assert.equal(body.status, 'misconfigured');
  assert.equal(body.commit, null);
}

{
  const reviewEnv = { ...env, XAGENT_REVIEW_ENABLED: 'true' };
  const res = await worker.fetch(
    new Request(`${ORIGIN}/xagent/agent-delivery-acceptance-audit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        task: 'Verify a read-only Worker delivery.',
        delivery_summary: 'Added version-bound health and proof endpoints.',
        artifacts: ['worker/index.mjs'],
        changed_files: ['worker/index.mjs'],
        validation: ['npm test'],
        validation_output: 'All tests passed.',
        hard_gates: ['no deploy without owner approval'],
        next_gate: 'Owner approves deployment.'
      })
    }),
    reviewEnv
  );
  assert.equal(res.status, 200);
  const body = await res.json();
  assert.equal(body.service_id, 'agent_delivery_acceptance_audit');
  assert.ok(['pass', 'needs_review', 'fail'].includes(body.verdict));
}

{
  const reviewEnv = { ...env, XAGENT_REVIEW_ENABLED: 'true' };
  const res = await worker.fetch(
    new Request(`${ORIGIN}/xagent/agent-delivery-acceptance-audit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ task: 'missing delivery summary' })
    }),
    reviewEnv
  );
  assert.equal(res.status, 400);
  const body = await res.json();
  assert.equal(body.error, 'bad_request');
  assert.match(body.message, /delivery_summary/);
}

{
  const res = await worker.fetch(
    new Request(`${ORIGIN}/xagent/agent-delivery-acceptance-audit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ task: 'disabled review route', delivery_summary: 'none' })
    }),
    env
  );
  assert.equal(res.status, 404);
}

console.log('PASS X-Agent deployment identity and review capability contract');
