import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const base = new URL(process.argv[2] ?? 'http://127.0.0.1:8789');
if (base.protocol !== 'http:' || base.hostname !== '127.0.0.1' || base.pathname !== '/' || base.username || base.password) {
  throw new Error('This smoke check is restricted to an HTTP server on 127.0.0.1.');
}
let passed = 0, failed = 0;
const fixture = async name => JSON.parse(await readFile(new URL(`../fixtures/${name}`, import.meta.url), 'utf8'));
const field = (target = 'result') => ({ source: 'value', target, type: 'string' });
const payload = value => ({ format: 'json', data: [{ value }], schema: [field()] });
async function call(path, options = {}) {
  const response = await fetch(new URL(path, base), { signal: AbortSignal.timeout(10000), ...options });
  return { status: response.status, headers: response.headers, body: await response.json() };
}
const post = (input, options = {}) => call('/v1/transform', {
  method: 'POST', headers: { 'content-type': 'application/json', ...options.headers },
  body: options.raw ?? JSON.stringify(input), ...(options.duplex ? { duplex: 'half' } : {}),
});
async function expectError(input, status, code, options) {
  const result = await post(input, options);
  assert.equal(result.status, status);
  assert.equal(result.body.error.code, code);
  assert.equal(Object.hasOwn(result.body, 'data'), false);
}
async function check(name, run) {
  try { await run(); passed++; process.stdout.write(`PASS ${name}\n`); }
  catch (error) { failed++; process.stderr.write(`FAIL ${name}: ${error.message}\n`); }
}

await check('CSV fixture matches the complete expected response', async () => {
  const result = await post(await fixture('csv-request.json'));
  assert.equal(result.status, 200);
  assert.deepEqual(result.body, await fixture('csv-expected.json'));
});
await check('JSON fixture converts types, trim, null and missing optional field', async () => {
  const result = await post(await fixture('json-request.json'));
  assert.equal(result.status, 200);
  assert.deepEqual(result.body.data, [{ id: '101', amount: 12.5, settled: false, note: null }, { id: '102', amount: 0, settled: true }]);
});
await check('invalid fixture returns 422 and both field errors', async () => {
  const result = await post(await fixture('invalid-request.json'));
  assert.equal(result.status, 422);
  assert.equal(result.body.error.details.totalErrors, 2);
  assert.equal(Object.hasOwn(result.body, 'data'), false);
});
for (const path of ['/health', '/.well-known/xagent-verification.json']) {
  await check(`${path} refuses unconfigured evidence`, async () => {
    const result = await call(path);
    assert.equal(result.status, 503);
    assert.equal(result.body.error.code, 'DEPLOYMENT_UNVERIFIED');
    assert.equal(Object.hasOwn(result.body, 'commit'), false);
    assert.equal(result.headers.get('cache-control'), 'no-store');
  });
}
await check('OpenAPI responds with all six paths', async () => {
  const result = await call('/openapi.json');
  assert.equal(result.status, 200);
  assert.equal(result.body.openapi, '3.1.0');
  assert.deepEqual(Object.keys(result.body.paths).sort(), ['/', '/docs', '/status', '/v1', '/.well-known/xagent-verification.json', '/health', '/openapi.json', '/v1/transform'].sort());
});
await check('quoted CSV newline and escaped quote survive the real runtime', async () => {
  const result = await post({ format: 'csv', data: 'value\r\n"tea,""green""\nline"\r\n', schema: [field()] });
  assert.equal(result.status, 200);
  assert.deepEqual(result.body.data, [{ result: 'tea,"green"\nline' }]);
});
await check('malformed CSV is rejected', () => expectError({ format: 'csv', data: 'value\n"unfinished', schema: [field()] }, 400, 'INVALID_CSV'));
await check('32 KiB request body is accepted', async () => {
  const raw = JSON.stringify(payload('x'));
  const result = await post(null, { raw: raw + ' '.repeat(32768 - Buffer.byteLength(raw)) });
  assert.equal(result.status, 200);
});
await check('32 KiB plus one request body is rejected', () => expectError(null, 413, 'BODY_LIMIT', { raw: ' '.repeat(32769) }));
await check('chunked oversized request is rejected without Content-Length', async () => {
  const raw = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(32769)); controller.close(); } });
  await expectError(null, 413, 'BODY_LIMIT', { raw, duplex: true });
});
await check('UTF-8 split into individual bytes reconstructs correctly', async () => {
  const bytes = Buffer.from(JSON.stringify(payload('茶 💡')));
  const raw = new ReadableStream({ start(controller) { for (const byte of bytes) controller.enqueue(Uint8Array.of(byte)); controller.close(); } });
  const result = await post(null, { raw, duplex: true });
  assert.equal(result.status, 200);
  assert.deepEqual(result.body.data, [{ result: '茶 💡' }]);
});
await check('invalid UTF-8 is rejected', () => expectError(null, 400, 'INVALID_BODY', { raw: Uint8Array.of(0xff) }));
for (const format of ['json', 'csv']) {
  for (const count of [100, 101]) {
    await check(`${format}: ${count}-row boundary`, async () => {
      const data = format === 'json' ? Array.from({ length: count }, () => ({ value: 'x' })) : `value\n${Array(count).fill('x').join('\n')}`;
      const input = { format, data, schema: [field()] };
      if (count === 101) await expectError(input, 413, 'ROW_LIMIT');
      else { const result = await post(input); assert.equal(result.status, 200); assert.equal(result.body.data.length, count); }
    });
  }
  for (const count of [20, 21]) {
    await check(`${format}: ${count}-field boundary`, async () => {
      const names = Array.from({ length: count }, (_, index) => `f${index}`);
      const data = format === 'json' ? [Object.fromEntries(names.map(name => [name, 'x']))] : `${names.join(',')}\n${names.map(() => 'x').join(',')}`;
      const input = { format, data, schema: [{ source: 'f0', target: 'result', type: 'string' }] };
      if (count === 21) await expectError(input, 413, 'FIELD_LIMIT');
      else assert.equal((await post(input)).status, 200);
    });
  }
  for (const count of [2048, 2049]) {
    await check(`${format}: ${count}-unit string boundary`, async () => {
      const data = format === 'json' ? [{ value: 'x'.repeat(count) }] : `value\n${'x'.repeat(count)}`;
      const input = { format, data, schema: [field()] };
      if (count === 2049) await expectError(input, 413, 'CELL_LIMIT');
      else assert.equal((await post(input)).status, 200);
    });
  }
}
await check('schema cannot exceed 20 mappings', () => expectError({ ...payload('x'), schema: Array.from({ length: 21 }, (_, index) => field(`f${index}`)) }, 400, 'INVALID_SCHEMA'));
await check('small input cannot amplify past the output byte budget', () => expectError({ ...payload('💡'.repeat(1000)), schema: Array.from({ length: 20 }, (_, index) => field(`f${index}`)) }, 413, 'OUTPUT_LIMIT'));
await check('wrong content type receives 415', () => expectError(payload('x'), 415, 'UNSUPPORTED_MEDIA_TYPE', { headers: { 'content-type': 'text/plain' } }));
await check('wrong method has Allow, and unknown path returns 404', async () => {
  const wrong = await call('/v1/transform');
  assert.equal(wrong.status, 405);
  assert.equal(wrong.headers.get('allow'), 'POST');
  assert.equal((await call('/not-a-route')).status, 404);
});
process.stdout.write(`\nLocal Workers HTTP smoke checks: ${passed} passed, ${failed} failed.\n`);
if (failed) process.exitCode = 1;
