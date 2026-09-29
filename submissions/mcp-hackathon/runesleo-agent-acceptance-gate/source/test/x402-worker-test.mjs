// Unit tests for the OKX x402 paywall using a mocked facilitator (no network,
// no credentials). Part of `npm test`.
//
// Covers:
//   1. X402_ENABLED=false → byte-identical free behavior (status + headers)
//   2. enabled + no payment → 402 by default (free trial opt-in only)
//   3. enabled + X402_FREE_TRIAL=true → one free POST, then 402
//   4. enabled + official `PAYMENT` header accepted
//   5. verify isValid=false → 402, settle never called
//   6. settle pending → settle/status poll → success → 200 delivered
//   7. settle timeout → still pending → 402 pending_tx; replay same payment
//      after confirmation → 200 delivered with NO second settle call
//   8. resource.url mismatch → 402, no facilitator calls
//   9. OKX envelope code!=="0" → 502 facilitator_error with generic code only

import assert from 'node:assert/strict';
import worker from '../worker/index.mjs';

const BASE = 'https://gate.example.com';
const RESOURCE = `${BASE}/world-cup-smart-money-radar`;

const ENV = {
  X402_ENABLED: 'true',
  OKX_API_KEY: 'test-key',
  OKX_SECRET_KEY: 'test-secret',
  OKX_PASSPHRASE: 'test-pass',
  X402_SETTLE_POLL_BUDGET_MS: '120',
  X402_SETTLE_POLL_INTERVAL_MS: '10'
};

// ---- facilitator mock ------------------------------------------------------

let script; // { verify, settle, status: [...] } — status entries shift()ed per call
let calls;

function okxEnvelope(data, code = '0') {
  return new Response(JSON.stringify({ code, msg: code === '0' ? '' : 'mock error', data }), {
    status: 200,
    headers: { 'content-type': 'application/json' }
  });
}

globalThis.fetch = async (input) => {
  const url = typeof input === 'string' ? input : input.url;
  if (url.startsWith('https://web3.okx.com/api/v6/pay/x402/')) {
    const path = new URL(url).pathname + new URL(url).search;
    if (path.startsWith('/api/v6/pay/x402/verify')) {
      calls.verify += 1;
      return script.verify();
    }
    if (path.startsWith('/api/v6/pay/x402/settle/status')) {
      calls.status += 1;
      const next = script.status.length > 1 ? script.status.shift() : script.status[0];
      return next();
    }
    if (path.startsWith('/api/v6/pay/x402/settle')) {
      calls.settle += 1;
      return script.settle();
    }
  }
  // Any other network call (live Polymarket fetch) fails → worker serves its
  // static fallback dataset, which is fine for these tests.
  throw new Error('external network disabled in tests');
};

function resetMock(overrides = {}) {
  calls = { verify: 0, settle: 0, status: 0 };
  script = {
    verify: () => okxEnvelope({ isValid: true, payer: '0x1111111111111111111111111111111111111111' }),
    settle: () => okxEnvelope({
      success: true, status: 'success', transaction: '0x' + 'ab'.repeat(32), network: 'eip155:196'
    }),
    status: [() => okxEnvelope({ success: true, status: 'success' })],
    ...overrides
  };
}

// ---- helpers ----------------------------------------------------------------

function paymentHeader({ nonce = '0x' + '11'.repeat(32), resourceUrl = undefined, amount = '100000' } = {}) {
  const now = Math.floor(Date.now() / 1000);
  const accepted = {
    scheme: 'exact',
    network: 'eip155:196',
    amount,
    asset: '0x779ded0c9e1022225f8e0630b35a9b54be713736',
    payTo: '0x1e1a2f7ac1bc6df29a1878c3f26b17dccdc16e15',
    maxTimeoutSeconds: 300,
    extra: { name: 'USD₮0', version: '1' }
  };
  const payload = {
    x402Version: 2,
    ...(resourceUrl ? { resource: { url: resourceUrl } } : {}),
    accepted,
    payload: {
      authorization: {
        from: '0x1111111111111111111111111111111111111111',
        to: accepted.payTo,
        value: accepted.amount,
        validAfter: String(now - 5),
        validBefore: String(now + 300),
        nonce
      },
      signature: '0x' + '22'.repeat(65)
    }
  };
  return Buffer.from(JSON.stringify(payload), 'utf8').toString('base64');
}

function post(headers = {}, env = ENV, body = { limit: 1 }) {
  return worker.fetch(new Request(RESOURCE, {
    method: 'POST',
    headers: { 'content-type': 'application/json', ...headers },
    body: JSON.stringify(body)
  }), env);
}

function decodeB64Json(value) {
  return JSON.parse(Buffer.from(value, 'base64').toString('utf8'));
}

let passed = 0;
function ok(name) {
  passed += 1;
  console.log(`PASS ${name}`);
}

// ---- 1. disabled → byte-identical free behavior -----------------------------

{
  resetMock();
  // null (not undefined) — undefined would trigger post()'s ENV default param
  for (const env of [{}, { X402_ENABLED: 'false' }, null]) {
    const res = await post({}, env);
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('access-control-allow-headers'), 'content-type');
    assert.equal(res.headers.get('access-control-expose-headers'), null);
    assert.equal(res.headers.get('payment-required'), null);
    assert.equal(res.headers.get('payment-response'), null);
    assert.equal(res.headers.get('content-type'), 'application/json; charset=utf-8');
    assert.equal(res.headers.get('access-control-allow-origin'), '*');
    assert.equal(res.headers.get('access-control-allow-methods'), 'GET, POST, OPTIONS');
    const body = await res.json();
    assert.equal(body.schema_version, '0.1');
    assert.equal(calls.verify + calls.settle + calls.status, 0);
  }
  // OPTIONS stays identical too when disabled
  const preflight = await worker.fetch(new Request(RESOURCE, { method: 'OPTIONS' }), {});
  assert.equal(preflight.status, 204);
  assert.equal(preflight.headers.get('access-control-allow-headers'), 'content-type');
  assert.equal(preflight.headers.get('access-control-expose-headers'), null);
  ok('X402_ENABLED=false keeps free behavior and original headers byte-identical');
}

// ---- 2. enabled, no payment → 402 by default (listing-safe) -------------------

{
  resetMock();
  const res = await post({ 'cf-connecting-ip': '203.0.113.49' });
  assert.equal(res.status, 402);
  const challengeHeader = res.headers.get('payment-required');
  assert.ok(challengeHeader, 'PAYMENT-REQUIRED header present');
  const decoded = decodeB64Json(challengeHeader);
  const body = await res.json();
  assert.deepEqual(decoded, body);
  assert.equal(body.x402Version, 2);
  assert.equal(body.error, 'Payment required');
  assert.equal(body.resource.url, RESOURCE);
  assert.equal(body.accepts[0].amount, '100000');
  assert.equal(calls.verify + calls.settle + calls.status, 0);
  ok('no payment → unpaid POST returns 402 when free trial disabled (default)');
}

// ---- 2b. X402_FREE_TRIAL=true → free trial once, then 402 --------------------

{
  resetMock();
  const trialEnv = { ...ENV, X402_FREE_TRIAL: 'true' };
  const trialIp = { 'cf-connecting-ip': '203.0.113.50' };
  const first = await post(trialIp, trialEnv);
  assert.equal(first.status, 200);
  const firstBody = await first.json();
  assert.equal(firstBody.billing?.mode, 'free_trial');
  assert.equal(firstBody.billing?.list_price_usdt, '0.1');
  assert.equal(calls.verify + calls.settle + calls.status, 0);

  const second = await post(trialIp, trialEnv);
  assert.equal(second.status, 402);
  const challengeHeader = second.headers.get('payment-required');
  assert.ok(challengeHeader, 'PAYMENT-REQUIRED header present');
  const decoded = decodeB64Json(challengeHeader);
  const body = await second.json();
  assert.deepEqual(decoded, body);
  assert.equal(body.x402Version, 2);
  assert.equal(body.error, 'Payment required');
  assert.equal(body.resource.url, RESOURCE);
  const req = body.accepts[0];
  assert.equal(req.amount, '100000');
  assert.equal(calls.verify + calls.settle + calls.status, 0);
  ok('X402_FREE_TRIAL=true → first POST free trial, second POST 402');
}

// ---- 3. official PAYMENT header + verify+settle success → 200 ----------------

{
  resetMock();
  const res = await post({ PAYMENT: paymentHeader({ nonce: '0x' + 'a1'.repeat(32), amount: '100000' }), 'cf-connecting-ip': '203.0.113.51' });
  assert.equal(res.status, 200);
  const settle = decodeB64Json(res.headers.get('payment-response'));
  assert.equal(settle.status, 'success');
  const body = await res.json();
  assert.equal(body.schema_version, '0.1');
  assert.equal(calls.verify, 1);
  assert.equal(calls.settle, 1);
  ok('PAYMENT header accepted; verify+settle success → 200 with PAYMENT-RESPONSE');
}

// ---- 4. verify rejects → 402, settle never called ----------------------------

{
  resetMock({ verify: () => okxEnvelope({ isValid: false, invalidReason: 'invalid_signature' }) });
  const res = await post({ 'payment-signature': paymentHeader({ nonce: '0x' + 'a2'.repeat(32), amount: '100000' }), 'cf-connecting-ip': '203.0.113.52' });
  assert.equal(res.status, 402);
  const body = await res.json();
  assert.equal(body.error, 'invalid_signature');
  assert.equal(calls.verify, 1);
  assert.equal(calls.settle, 0);
  ok('verify isValid=false → 402 challenge, no settle');
}

// ---- 5. settle pending → poll settle/status → success → 200 ------------------

{
  resetMock({
    settle: () => okxEnvelope({
      success: false, status: 'pending', transaction: '0x' + 'b1'.repeat(32), network: 'eip155:196'
    }),
    status: [
      () => okxEnvelope({ success: true, status: 'pending' }),
      () => okxEnvelope({ success: true, status: 'success' })
    ]
  });
  const res = await post({ PAYMENT: paymentHeader({ nonce: '0x' + 'a3'.repeat(32), amount: '100000' }), 'cf-connecting-ip': '203.0.113.53' });
  assert.equal(res.status, 200);
  assert.ok(calls.status >= 2, 'polled settle/status until success');
  const settle = decodeB64Json(res.headers.get('payment-response'));
  assert.equal(settle.status, 'success');
  ok('settle pending → status poll confirms → 200 (pending alone never delivers)');
}

// ---- 6. settle timeout → 402 pending_tx → replay collects without re-settle --

{
  const tx = '0x' + 'c1'.repeat(32);
  resetMock({
    settle: () => okxEnvelope({ success: false, status: 'timeout', transaction: tx, network: 'eip155:196' }),
    status: [() => okxEnvelope({ success: true, status: 'pending' })]
  });
  const header = paymentHeader({ nonce: '0x' + 'a4'.repeat(32), amount: '100000' });
  const res = await post({ PAYMENT: header, 'cf-connecting-ip': '203.0.113.54' });
  assert.equal(res.status, 402);
  const body = await res.json();
  assert.equal(body.error, 'settlement_pending');
  assert.equal(body.status, 'pending_tx');
  assert.equal(body.transaction, tx);
  assert.equal(body.retry.retry_with_same_payment, true);
  assert.equal(calls.settle, 1);

  // tx confirms; buyer replays the SAME payment header
  script.status = [() => okxEnvelope({ success: true, status: 'success' })];
  const replay = await post({ PAYMENT: header });
  assert.equal(replay.status, 200);
  const replayBody = await replay.json();
  assert.equal(replayBody.schema_version, '0.1');
  assert.equal(calls.settle, 1, 'no second settle on replay');
  assert.equal(calls.verify, 1, 'no second verify on replay');
  const settle = decodeB64Json(replay.headers.get('payment-response'));
  assert.equal(settle.status, 'success');

  // and a third replay hits the success receipt directly (no facilitator calls)
  const statusCallsBefore = calls.status;
  const third = await post({ PAYMENT: header });
  assert.equal(third.status, 200);
  assert.equal(calls.status, statusCallsBefore, 'success receipt served without facilitator');
  ok('settle timeout → 402 pending_tx + txHash; replay same payment → delivered without re-settle');
}

// ---- 7. resource mismatch → 402, no facilitator calls ------------------------

{
  resetMock();
  const res = await post({
    PAYMENT: paymentHeader({ nonce: '0x' + 'a5'.repeat(32), amount: '100000', resourceUrl: `${BASE}/polymarket-smart-money-radar` }),
    'cf-connecting-ip': '203.0.113.55'
  });
  assert.equal(res.status, 402);
  const body = await res.json();
  assert.match(body.error, /resource mismatch/i);
  assert.equal(calls.verify + calls.settle + calls.status, 0);
  ok('payment signed for another resource → 402, facilitator untouched');
}

// ---- 8. OKX envelope business error → 502 generic ----------------------------

{
  resetMock({ verify: () => okxEnvelope(null, '50113') });
  const res = await post({ PAYMENT: paymentHeader({ nonce: '0x' + 'a6'.repeat(32), amount: '100000' }), 'cf-connecting-ip': '203.0.113.56' });
  assert.equal(res.status, 502);
  const body = await res.json();
  assert.equal(body.error, 'facilitator_error');
  assert.equal(body.operation, 'verify');
  assert.equal(body.code, 'okx_business_50113');
  assert.equal(body.message, undefined, 'no upstream body excerpt leaks');
  ok('OKX code!=="0" on HTTP 200 → 502 facilitator_error with generic code only');
}

console.log(`All ${passed} x402 worker test groups passed`);
