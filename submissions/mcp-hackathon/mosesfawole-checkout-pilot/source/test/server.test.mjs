import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createAppServer, validatePaymentInput } from '../server.mjs';

test('validates and canonicalizes decimal-string amounts', () => {
  const result = validatePaymentInput({ amount: '049.5', item: 'Pilot', reference: 'INV-1' });
  assert.equal(result.ok, true);
  assert.equal(result.value.toAmount, '49.50');
  assert.equal(result.value.description, 'INV-1 | Pilot');
  assert.equal(result.value.maxUsage, 1);
});

test('rejects non-positive, numeric, and over-precise amounts', () => {
  for (const amount of ['0', '0.00', '-1', '1.001', 'abc']) {
    assert.equal(validatePaymentInput({ amount }).ok, false, amount);
  }
  assert.equal(validatePaymentInput({ toAmount: 49.99 }).ok, false);
});

test('demo API creates, reads, and settles a payment link', async (t) => {
  const server = createAppServer({ env: {} });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;

  const config = await fetch(`${base}/api/config`).then((response) => response.json());
  assert.equal(config.mode, 'demo');

  const health = await fetch(`${base}/health`).then((response) => response.json());
  assert.equal(health.status, 'ok');
  assert.equal(health.commit, 'development');

  const createResponse = await fetch(`${base}/api/payment-links`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ amount: '25', item: 'Workshop seat', reference: 'TEST-25' })
  });
  assert.equal(createResponse.status, 201);
  const created = await createResponse.json();
  assert.match(created.id, /^demo-/);
  assert.equal(created.status, 'active');
  assert.equal(created.toAmount, '25.00');
  assert.match(created.url, new RegExp(`^${base.replaceAll('.', '\\.')}\/pay\/demo-`));

  const fetched = await fetch(`${base}/api/payment-links/${created.id}`).then((response) => response.json());
  assert.equal(fetched.description, 'TEST-25 | Workshop seat');

  const settledResponse = await fetch(`${base}/api/payment-links/${created.id}/simulate`, { method: 'POST' });
  assert.equal(settledResponse.status, 200);
  const settled = await settledResponse.json();
  assert.equal(settled.status, 'completed');
  assert.equal(settled.receivedAmount, '25.00');

  const pageResponse = await fetch(created.url);
  assert.equal(pageResponse.status, 200);
  assert.match(await pageResponse.text(), /Checkout Pilot/);
});

test('serves X-Agent deployment proof only for a real source commit', async (t) => {
  const commit = 'a'.repeat(40);
  const server = createAppServer({
    env: { SOURCE_COMMIT: commit, XAGENT_SUBMISSION_SLUG: 'builder-checkout-pilot' }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const { port } = server.address();
  const base = `http://127.0.0.1:${port}`;

  const health = await fetch(`${base}/health`).then((response) => response.json());
  assert.equal(health.commit, commit);

  const proofResponse = await fetch(`${base}/.well-known/xagent-verification.json`);
  assert.equal(proofResponse.status, 200);
  assert.deepEqual(await proofResponse.json(), {
    schemaVersion: 1,
    slug: 'builder-checkout-pilot',
    commit
  });
});

test('documents agent capability boundaries', async (t) => {
  const server = createAppServer({ env: {} });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const { port } = server.address();
  const body = await fetch(`http://127.0.0.1:${port}/api/capabilities`).then((response) => response.json());
  assert.deepEqual(body.operations.map((operation) => operation.id), [
    'create_payment_request',
    'get_payment_request'
  ]);
  assert.match(body.sideEffects.createPaymentRequest, /never sends/);
});

test('rejects invalid payment input without creating a record', async (t) => {
  const server = createAppServer({ env: {} });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const { port } = server.address();
  const response = await fetch(`http://127.0.0.1:${port}/api/payment-links`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ amount: '12.345' })
  });
  assert.equal(response.status, 400);
  assert.match((await response.json()).error, /Amount/);
});

test('does not silently fall back to demo when live configuration is partial', async (t) => {
  const server = createAppServer({ env: { MOOVE_API_KEY: 'present-but-not-used' } });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const { port } = server.address();
  const config = await fetch(`http://127.0.0.1:${port}/api/config`).then((response) => response.json());
  assert.equal(config.mode, 'misconfigured');
  const response = await fetch(`http://127.0.0.1:${port}/api/payment-links`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ amount: '1.00' })
  });
  assert.equal(response.status, 503);
});

test('does not allow a non-local HTTP API base for live credentials', async (t) => {
  const server = createAppServer({ env: { MOOVE_API_BASE_URL: 'http://api.example.test', MOOVE_API_KEY: 'present-but-not-used' } });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => server.close(resolve)));
  const { port } = server.address();
  const config = await fetch(`http://127.0.0.1:${port}/api/config`).then((response) => response.json());
  assert.equal(config.mode, 'misconfigured');
});

test('live mode forwards the exact Receive contract server-side', async (t) => {
  let receivedHeaders;
  let receivedBody;
  const moove = http.createServer(async (req, res) => {
    receivedHeaders = req.headers;
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    receivedBody = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    res.writeHead(201, { 'content-type': 'application/json' });
    res.end(JSON.stringify({ id: 'live-1', url: 'https://www.moove.xyz/@pilot/pay/live-1', status: 'active' }));
  });
  await new Promise((resolve) => moove.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => moove.close(resolve)));
  const moovePort = moove.address().port;

  const app = createAppServer({
    env: { MOOVE_API_BASE_URL: `http://127.0.0.1:${moovePort}`, MOOVE_API_KEY: 'mk_test_server_only' }
  });
  await new Promise((resolve) => app.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise((resolve) => app.close(resolve)));
  const appPort = app.address().port;

  const response = await fetch(`http://127.0.0.1:${appPort}/api/payment-links`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ amount: '12.5', item: 'Test order', reference: 'LIVE-1' })
  });
  assert.equal(response.status, 201);
  assert.equal((await response.json()).id, 'live-1');
  assert.equal(receivedHeaders['x-api-key'], 'mk_test_server_only');
  assert.deepEqual(receivedBody, {
    toAmount: '12.50',
    description: 'LIVE-1 | Test order',
    maxUsage: 1,
    expirationDate: null
  });
});
