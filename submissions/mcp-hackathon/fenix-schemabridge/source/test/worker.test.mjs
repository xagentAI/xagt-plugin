import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { once } from 'node:events';
import worker from '../src/worker.mjs';
import { LIMITS } from '../src/transform.mjs';
import { makeServer, localAssets } from '../tools/serve.mjs';

const fixture = async name => JSON.parse(await readFile(new URL(`../fixtures/${name}`, import.meta.url), 'utf8'));
const mapping = (type = 'string', extra = {}) => ({ source: 'value', target: 'result', type, ...extra });
const payload = (value, type = 'string', extra = {}) => ({ format: 'json', data: [{ value }], schema: [mapping(type, extra)] });
async function post(input, options = {}) {
  const response = await worker.fetch(new Request('http://localhost/v1/transform', {
    method: 'POST', headers: { 'content-type': 'application/json', ...options.headers },
    body: options.raw ?? JSON.stringify(input), ...(options.duplex ? { duplex: options.duplex } : {}),
  }));
  return { response, body: await response.json() };
}
async function error(input, status, code, options) {
  const actual = await post(input, options);
  assert.equal(actual.response.status, status);
  assert.equal(actual.body.error.code, code);
  assert.equal(actual.body.ok, false);
  assert.equal(Object.hasOwn(actual.body, 'data'), false);
  return actual.body;
}

test('CSV fixture transforms exactly, including zero and false', async () => {
  const actual = await post(await fixture('csv-request.json'));
  assert.equal(actual.response.status, 200);
  assert.deepEqual(actual.body, await fixture('csv-expected.json'));
});

test('JSON fixture distinguishes null, missing optional and explicit trim', async () => {
  const actual = await post(await fixture('json-request.json'));
  assert.deepEqual(actual.body.data, [{ id: '101', amount: 12.5, settled: false, note: null }, { id: '102', amount: 0, settled: true }]);
  assert.equal(actual.body.summary.convertedCells, 4);
});

test('conversion rules accept each documented primitive type', async () => {
  for (const [value, type, expected] of [
    ['-42', 'integer', -42], [Number.MAX_SAFE_INTEGER, 'integer', Number.MAX_SAFE_INTEGER],
    ['1.25e2', 'number', 125], ['-0.01', 'number', -0.01],
    ['false', 'boolean', false], [true, 'boolean', true],
    [false, 'string', 'false'], [12.5, 'string', '12.5'], ['', 'string', ''],
  ]) {
    const actual = await post(payload(value, type));
    assert.equal(actual.response.status, 200, `${type}: ${value}`);
    assert.equal(actual.body.data[0].result, expected);
  }
});

test('integer conversion rejects unsafe numbers and noncanonical integer strings', async () => {
  for (const value of ['9007199254740993', 9007199254740992, '1.0', '1e2', '01', '+1', true, ' 1 ', '']) {
    await error(payload(value, 'integer'), 422, 'VALIDATION_FAILED');
  }
});

test('raw JSON numbers are validated after IEEE-754 parsing; strings retain exact spelling', async () => {
  for (const [literal, expected] of [
    ['1.0000000000000001', 1], ['9007199254740990.5', 9007199254740990],
    ['9007199254740991.1', 9007199254740991], ['1.0', 1], ['1e2', 100],
  ]) {
    const raw = `{"format":"json","data":[{"value":${literal}}],"schema":[{"source":"value","target":"result","type":"integer"}]}`;
    const actual = await post(null, { raw });
    assert.equal(actual.response.status, 200, literal);
    assert.equal(actual.body.data[0].result, expected);
    assert.equal(actual.body.summary.convertedCells, 0);
    await error(payload(literal, 'integer'), 422, 'VALIDATION_FAILED');
  }
});

test('number conversion rejects non-decimal and non-finite forms', async () => {
  for (const value of ['Infinity', 'NaN', '1e999', '0x10', '01', '+1', '1.', '.5', '', true]) {
    await error(payload(value, 'number'), 422, 'VALIDATION_FAILED');
  }
  await error(null, 400, 'NONFINITE_NUMBER', { raw: '{"format":"json","data":[{"value":1e999}],"schema":[{"source":"value","target":"result","type":"number"}]}' });
});

test('boolean conversion is exact and trim is opt-in', async () => {
  for (const value of ['TRUE', 'yes', '1', 1, ' false ']) await error(payload(value, 'boolean'), 422, 'VALIDATION_FAILED');
  assert.equal((await post(payload(' false ', 'boolean', { trim: true }))).body.data[0].result, false);
  assert.equal((await post(payload(' x '))).body.data[0].result, ' x ');
});

test('missing required, null and empty string remain distinct', async () => {
  const missing = await error({ format: 'json', data: [{}], schema: [mapping()] }, 422, 'VALIDATION_FAILED');
  assert.equal(missing.error.details.fields[0].code, 'MISSING_FIELD');
  assert.equal((await error(payload(null), 422, 'VALIDATION_FAILED')).error.details.fields[0].code, 'NULL_NOT_ALLOWED');
  assert.equal((await post(payload(null, 'integer', { nullable: true }))).body.data[0].result, null);
  assert.deepEqual((await post({ format: 'json', data: [{}], schema: [mapping('string', { required: false })] })).body.data, [{}]);
});

test('validation is atomic and reports bounded locations without cell values', async () => {
  const input = { format: 'json', data: Array.from({ length: 60 }, () => ({ value: 'private-cell-example' })), schema: [mapping('integer')] };
  const actual = await error(input, 422, 'VALIDATION_FAILED');
  assert.equal(actual.error.details.totalErrors, 60);
  assert.equal(actual.error.details.fields.length, LIMITS.errorDetails);
  assert.equal(actual.error.details.truncated, true);
  assert.equal(actual.error.details.fields[0].row, 0);
  assert.equal(JSON.stringify(actual).includes('private-cell-example'), false);
});

test('CSV supports BOM, escaped quotes, quoted LF/CRLF and a trailing line ending', async () => {
  const input = { format: 'csv', data: '\uFEFFvalue\r\n"a,""b""\nline\r\nend"\r\n', schema: [mapping()] };
  const actual = await post(input);
  assert.equal(actual.response.status, 200);
  assert.deepEqual(actual.body.data, [{ result: 'a,"b"\nline\r\nend' }]);
});

test('CSV rejects broken quoting and bare CR, rather than silently repairing it', async () => {
  for (const data of ['value\n"open', 'value\na"b', 'value\n"a"oops', 'value\ra']) {
    await error({ format: 'csv', data, schema: [mapping()] }, 400, 'INVALID_CSV');
  }
});

test('CSV rejects duplicate, empty and unsafe headers plus ragged rows', async () => {
  for (const data of ['value,value\na,b', ',value\na,b', '__proto__\nx', `${'x'.repeat(65)}\nx`]) {
    await error({ format: 'csv', data, schema: [mapping()] }, 400, 'INVALID_CSV_HEADER');
  }
  for (const data of ['value,other\nx', 'value\nx,y']) await error({ format: 'csv', data, schema: [mapping()] }, 400, 'CSV_COLUMN_COUNT');
});

test('empty record sets and header-only CSV are valid; empty CSV is not', async () => {
  for (const [format, data] of [['json', []], ['csv', 'value'], ['csv', 'value\n']]) {
    const actual = await post({ format, data, schema: [mapping()] });
    assert.equal(actual.response.status, 200);
    assert.deepEqual(actual.body.data, []);
  }
  await error({ format: 'csv', data: '', schema: [mapping()] }, 400, 'INVALID_CSV');
});

test('CSV blank records and trailing empty cells are not silently dropped', async () => {
  assert.deepEqual((await post({ format: 'csv', data: 'value\n\n', schema: [mapping()] })).body.data, [{ result: '' }]);
  assert.deepEqual((await post({ format: 'csv', data: 'first,value\nx,', schema: [mapping()] })).body.data, [{ result: '' }]);
});

test('schema rejects unknown options, duplicate targets and unsafe names', async () => {
  for (const schema of [[], [mapping('date')], [mapping('string', { trim: 'yes' })], [mapping('string', { expression: 'process.env' })], [mapping('string', { source: '' })]]) {
    await error({ format: 'json', data: [], schema }, 400, 'INVALID_SCHEMA');
  }
  for (const name of ['__proto__', 'constructor', 'prototype']) {
    await error({ format: 'json', data: [], schema: [mapping('string', { target: name })] }, 400, 'INVALID_SCHEMA');
    await error(null, 400, 'INVALID_FIELD_NAME', { raw: JSON.stringify({ format: 'json', data: [JSON.parse(`{"${name}":"x"}`)], schema: [mapping()] }) });
  }
  await error({ format: 'json', data: [], schema: [mapping(), mapping('integer')] }, 400, 'DUPLICATE_TARGET');
  assert.equal(Object.prototype.polluted, undefined);
});

test('unknown envelope fields, wrong data format and nested cells are rejected', async () => {
  await error({ ...payload('x'), fetchUrl: 'https://example.com' }, 400, 'INVALID_REQUEST');
  await error({ ...payload('x'), format: 'xml' }, 400, 'INVALID_REQUEST');
  await error({ ...payload('x'), data: 'x' }, 400, 'INVALID_DATA');
  await error({ ...payload('x'), data: [null] }, 400, 'INVALID_ROW');
  for (const value of [{ nested: true }, ['x']]) await error(payload(value), 400, 'NESTED_VALUE');
});

test('row limit is inclusive for JSON and CSV', async () => {
  for (const count of [100, 101]) {
    const json = { format: 'json', data: Array.from({ length: count }, () => ({ value: 'x' })), schema: [mapping()] };
    const csv = { format: 'csv', data: `value\n${Array(count).fill('x').join('\n')}`, schema: [mapping()] };
    for (const input of [json, csv]) {
      if (count === 100) assert.equal((await post(input)).body.data.length, 100);
      else await error(input, 413, 'ROW_LIMIT');
    }
  }
});

test('field limits are inclusive for input rows, CSV and schema', async () => {
  for (const count of [20, 21]) {
    const names = Array.from({ length: count }, (_, index) => `f${index}`);
    const row = Object.fromEntries(names.map(name => [name, 'x']));
    const schema = [{ source: 'f0', target: 'result', type: 'string' }];
    const json = { format: 'json', data: [row], schema };
    const csv = { format: 'csv', data: `${names.join(',')}\n${names.map(() => 'x').join(',')}`, schema };
    for (const input of [json, csv]) {
      if (count === 20) assert.equal((await post(input)).response.status, 200);
      else await error(input, 413, 'FIELD_LIMIT');
    }
    const manyMappings = { format: 'json', data: [], schema: names.map(name => ({ source: name, target: name, type: 'string' })) };
    if (count === 20) assert.equal((await post(manyMappings)).response.status, 200);
    else await error(manyMappings, 400, 'INVALID_SCHEMA');
  }
});

test('cell and name length limits accept boundary and reject the next unit', async () => {
  for (const length of [2048, 2049]) {
    for (const input of [payload('x'.repeat(length)), { format: 'csv', data: `value\n${'x'.repeat(length)}`, schema: [mapping()] }]) {
      if (length === 2048) assert.equal((await post(input)).response.status, 200);
      else await error(input, 413, 'CELL_LIMIT');
    }
  }
  const name = 'x'.repeat(64);
  assert.equal((await post({ format: 'json', data: [{ [name]: 'x' }], schema: [{ source: name, target: name, type: 'string' }] })).response.status, 200);
  await error({ format: 'json', data: [{ [name + 'x']: 'x' }], schema: [mapping()] }, 400, 'INVALID_FIELD_NAME');
});

test('UTF-8 body byte budget is inclusive and counts bytes rather than string length', async () => {
  const base = JSON.stringify(payload('x'));
  assert.equal((await post(null, { raw: base + ' '.repeat(LIMITS.bodyBytes - Buffer.byteLength(base)) })).response.status, 200);
  await error(null, 413, 'BODY_LIMIT', { raw: base + ' '.repeat(LIMITS.bodyBytes - Buffer.byteLength(base) + 1) });
  await error(null, 413, 'BODY_LIMIT', { raw: JSON.stringify(payload('💡'.repeat(8200))) });
});

test('streamed bodies enforce limit without a Content-Length header', async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(LIMITS.bodyBytes + 1)); },
    cancel() { cancelled = true; },
  });
  await error(null, 413, 'BODY_LIMIT', { raw: stream, duplex: 'half' });
  assert.equal(cancelled, true);
});

test('content type, compression and invalid UTF-8/JSON produce clear errors', async () => {
  await error(payload('x'), 415, 'UNSUPPORTED_MEDIA_TYPE', { headers: { 'content-type': 'text/csv' } });
  await error(payload('x'), 415, 'UNSUPPORTED_ENCODING', { headers: { 'content-encoding': 'gzip' } });
  await error(null, 400, 'INVALID_BODY', { raw: new Uint8Array([0xff]) });
  await error(null, 400, 'INVALID_JSON', { raw: '{' });
  await error(null, 400, 'INVALID_JSON', { raw: '' });
  await error(payload('x'), 413, 'BODY_LIMIT', { headers: { 'content-length': '32769' } });
  assert.equal((await post(payload('x'), { headers: { 'content-type': 'Application/JSON; charset=utf-8' } })).response.status, 200);
});

test('invalid UTF-8 cancels the remaining body stream', async () => {
  let cancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array([0xff])); },
    cancel() { cancelled = true; },
  });
  await error(null, 400, 'INVALID_BODY', { raw: stream, duplex: 'half' });
  assert.equal(cancelled, true);
});

test('output amplification has a byte limit even when the input is small', async () => {
  const schema = Array.from({ length: 20 }, (_, index) => mapping('string', { target: `f${index}` }));
  const below = { format: 'json', data: [{ value: 'x'.repeat(1500) }], schema };
  const actual = await post(below);
  assert.equal(actual.response.status, 200);
  assert.ok(Buffer.byteLength(JSON.stringify(actual.body)) <= LIMITS.outputBytes);
  await error({ ...below, data: [{ value: '💡'.repeat(1000) }] }, 413, 'OUTPUT_LIMIT');
});

test('proof routes refuse absent, malformed or zero commit and missing slug', async () => {
  for (const path of ['/health', '/.well-known/xagent-verification.json']) {
    for (const commit of [undefined, '', 'abc123', 'g'.repeat(40), '0'.repeat(40)]) {
      const response = await worker.fetch(new Request(`http://localhost${path}`), { REVIEW_COMMIT: commit, PROJECT_SLUG: 'fenix-schemabridge' });
      assert.equal(response.status, 503);
      const body = await response.json();
      assert.equal(body.error.code, 'DEPLOYMENT_UNVERIFIED');
      assert.equal(Object.hasOwn(body, 'commit'), false);
      assert.equal(Object.hasOwn(body, 'status'), false);
    }
  }
  const response = await worker.fetch(new Request('http://localhost/.well-known/xagent-verification.json'), { REVIEW_COMMIT: '1234567890abcdef1234567890abcdef12345678' });
  assert.equal(response.status, 503);
});

test('configured proof routes preserve the supplied SHA and exact X-Agent shapes', async () => {
  // Synthetic test value only; it is not represented as a real source commit.
  const commit = '1234567890abcdef1234567890abcdef12345678';
  const env = { REVIEW_COMMIT: commit, PROJECT_SLUG: 'fenix-schemabridge' };
  for (const [path, expected] of [
    ['/health', { status: 'ok', commit }],
    ['/.well-known/xagent-verification.json', { schemaVersion: 1, slug: 'fenix-schemabridge', commit }],
  ]) {
    const response = await worker.fetch(new Request(`http://localhost${path}`), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get('cache-control'), 'no-store');
    assert.deepEqual(await response.json(), expected);
  }
});

test('methods, unknown routes and OpenAPI are explicit', async () => {
  for (const path of ['/', '/docs', '/status', '/assets/app.css', '/assets/app.js', '/assets/docs.css', '/assets/status.js', '/v1', '/health', '/.well-known/xagent-verification.json', '/openapi.json']) {
    const response = await worker.fetch(new Request(`http://localhost${path}`, { method: 'POST' }));
    assert.equal(response.status, 405);
    assert.equal(response.headers.get('allow'), 'GET');
  }
  const wrong = await worker.fetch(new Request('http://localhost/v1/transform'));
  assert.equal(wrong.status, 405);
  assert.equal(wrong.headers.get('allow'), 'POST');
  assert.equal((await worker.fetch(new Request('http://localhost/unknown'))).status, 404);
  const response = await worker.fetch(new Request('http://localhost/openapi.json'));
  assert.equal(response.status, 200);
  const document = await response.json();
  assert.equal(document.openapi, '3.1.0');
  assert.deepEqual(Object.keys(document.paths).sort(), ['/', '/docs', '/status', '/v1', '/.well-known/xagent-verification.json', '/health', '/openapi.json', '/v1/transform'].sort());
  for (const path of ['/v1']) {
    const index = await worker.fetch(new Request(`http://localhost${path}`));
    assert.equal(index.status, 200);
    const body = await index.json();
    assert.deepEqual(body.capability, { method: 'POST', path: '/v1/transform', contentType: 'application/json' });
    assert.deepEqual(body.limits, { requestBytes: 32768, records: 100 });
    assert.equal(body.documentation, '/openapi.json');
  }
});

test('homepage and its local assets are served as a restricted browser interface', async () => {
  const response = await worker.fetch(new Request('http://localhost/'));
  assert.equal(response.status, 200);
  assert.match(response.headers.get('content-type'), /^text\/html;/);
  assert.equal(response.headers.get('cache-control'), 'no-store');
  const csp = response.headers.get('content-security-policy');
  assert.match(csp, /script-src 'self'/);
  assert.match(csp, /connect-src 'self'/);
  assert.match(csp, /img-src 'self'/);
  assert.match(csp, /font-src 'self'/);
  assert.match(csp, /frame-ancestors 'none'/);
  assert.doesNotMatch(csp, /unsafe-inline|unsafe-eval/);
  const html = await response.text();
  assert.match(html, /lang="en"/);
  assert.doesNotMatch(html, /[\u0400-\u04ff]|data-language|language-switch/);
  assert.match(html, /<main[\s>]/);
  assert.match(html, /<textarea[\s>]/);
  assert.match(html, /src="\/assets\/app\.js"/);
  assert.match(html, /href="\/assets\/app\.css"/);
  assert.doesNotMatch(html, /<script(?![^>]*src=)[^>]*>|\sonclick=|chatgpt\.site/i);
  for (const [path, type] of [['/assets/app.css', 'text/css'], ['/assets/app.js', 'text/javascript']]) {
    const asset = await worker.fetch(new Request(`http://localhost${path}`));
    assert.equal(asset.status, 200);
    assert.ok(asset.headers.get('content-type').startsWith(type));
    assert.equal(asset.headers.get('x-content-type-options'), 'nosniff');
    const assetText = await asset.text();
    assert.ok(assetText.length > 0);
    assert.doesNotMatch(assetText, /[\u0400-\u04ff]|data-language|language-switch/);
  }
  const path = '/assets/schema-sculpture.png';
  const env = { ASSETS: localAssets };
  const bytes = await readFile(new URL('../public/assets/schema-sculpture.png', import.meta.url));
  const image = await worker.fetch(new Request(`http://localhost${path}`), env);
  assert.equal(image.status, 200);
  assert.equal(image.headers.get('content-type'), 'image/png');
  assert.equal(image.headers.get('x-content-type-options'), 'nosniff');
  assert.equal(Number(image.headers.get('content-length')), bytes.length);
  assert.deepEqual(Buffer.from(await image.arrayBuffer()), bytes);
  assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
  const head = await worker.fetch(new Request(`http://localhost${path}`, { method: 'HEAD' }), env);
  assert.equal(head.status, 200);
  assert.equal(Number(head.headers.get('content-length')), bytes.length);
  assert.equal((await head.arrayBuffer()).byteLength, 0);
  const unsupported = await worker.fetch(new Request(`http://localhost${path}`, { method: 'POST' }), env);
  assert.equal(unsupported.status, 405);
  assert.equal(unsupported.headers.get('allow'), 'GET, HEAD');
  assert.equal((await worker.fetch(new Request(`http://localhost${path}`))).status, 503);
  for (const font of ['instrument-sans-latin.woff2', 'instrument-serif-latin.woff2', 'instrument-serif-italic-latin.woff2']) {
    const response = await worker.fetch(new Request(`http://localhost/assets/fonts/${font}`), env);
    assert.equal(response.status, 200, font);
    assert.equal(response.headers.get('content-type'), 'font/woff2');
    const bytes = Buffer.from(await response.arrayBuffer());
    assert.equal(bytes.subarray(0, 4).toString(), 'wOF2');
    assert.deepEqual(bytes, await readFile(new URL(`../public/assets/fonts/${font}`, import.meta.url)));
  }
  for (const denied of ['/src/worker.mjs', '/package.json', '/.env', '/assets/../../package.json', '/assets/unknown.png']) {
    assert.equal((await worker.fetch(new Request(`http://localhost${denied}`), env)).status, 404, denied);
    assert.equal((await localAssets.fetch(new Request(`http://localhost${denied}`))).status, 404, denied);
  }
});

test('independent requests do not retain record state', async () => {
  const [first, second] = await Promise.all([post(payload('first')), post(payload('second'))]);
  assert.deepEqual(first.body.data, [{ result: 'first' }]);
  assert.deepEqual(second.body.data, [{ result: 'second' }]);
});

test('all local page links and fragments resolve to available resources', async () => {
  const env = { REVIEW_COMMIT: '1234567890abcdef1234567890abcdef12345678', PROJECT_SLUG: 'fenix-schemabridge', ASSETS: localAssets };
  const bodies = new Map();
  for (const path of ['/', '/docs', '/status']) {
    const response = await worker.fetch(new Request(`http://localhost${path}`), env);
    assert.equal(response.status, 200, path);
    assert.match(response.headers.get('content-type'), /^text\/html;/);
    const html = await response.text();
    assert.match(html, /lang="en"/);
    assert.doesNotMatch(html, /[\u0400-\u04ff]/);
    bodies.set(path, html);
  }
  for (const [path, html] of bodies) {
    for (const match of html.matchAll(/(?:href|src)="([^"]+)"/g)) {
      const target = new URL(match[1], `http://localhost${path}`);
      if (target.origin !== 'http://localhost') {
        assert.equal(target.protocol, 'https:');
        assert.equal(target.hostname, 'github.com');
        continue;
      }
      const response = await worker.fetch(new Request(target), env);
      assert.equal(response.status, 200, `${path} -> ${match[1]}`);
      if (target.hash) {
        const body = bodies.get(target.pathname) ?? await response.text();
        assert.ok(body.includes(`id="${decodeURIComponent(target.hash.slice(1))}"`), `Missing anchor: ${match[1]}`);
      }
    }
  }
});

test('documentation CSV and JSON requests are executable examples', async () => {
  const html = await (await worker.fetch(new Request('http://localhost/docs'))).text();
  function example(id) {
    const match = html.match(new RegExp(`<pre[^>]*id="${id}"[^>]*>([\\s\\S]*?)</pre>`));
    assert.ok(match, `Missing example ${id}`);
    return JSON.parse(match[1].replace(/<\/?code[^>]*>/g, '').replaceAll('&quot;', '"').replaceAll('&#39;', "'").replaceAll('&lt;', '<').replaceAll('&gt;', '>').replaceAll('&amp;', '&'));
  }
  for (const id of ['csv-request-example', 'json-request-example']) {
    const requestBody = example(id);
    const response = await worker.fetch(new Request('http://localhost/v1/transform', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(requestBody) }));
    assert.equal(response.status, 200, id);
    const body = await response.json();
    assert.equal(body.ok, true);
    assert.deepEqual(body, example(id.replace('request', 'response')), id);
  }
  const invalid = example('csv-request-example');
  invalid.data = invalid.data.replace(',7,true', ',seven,true');
  const response = await worker.fetch(new Request('http://localhost/v1/transform', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(invalid) }));
  assert.equal(response.status, 422);
  assert.deepEqual(await response.json(), example('error-response-example'));
});

test('local HTTP adapter exposes the real handler and body limit on loopback', async t => {
  const server = makeServer();
  server.listen(0, '127.0.0.1');
  await once(server, 'listening');
  t.after(() => { server.closeAllConnections(); server.close(); });
  const base = `http://127.0.0.1:${server.address().port}`;
  assert.equal((await fetch(`${base}/health`)).status, 503);
  assert.equal((await fetch(`${base}/.well-known/xagent-verification.json`)).status, 503);
  const illustration = await fetch(`${base}/assets/schema-sculpture.png`);
  assert.equal(illustration.status, 200);
  assert.equal(illustration.headers.get('content-type'), 'image/png');
  assert.deepEqual(Buffer.from(await illustration.arrayBuffer()), await readFile(new URL('../public/assets/schema-sculpture.png', import.meta.url)));
  const illustrationHead = await fetch(`${base}/assets/schema-sculpture.png`, { method: 'HEAD' });
  assert.equal(illustrationHead.status, 200);
  assert.equal((await illustrationHead.arrayBuffer()).byteLength, 0);
  assert.equal((await fetch(`${base}/package.json`)).status, 404);
  const response = await fetch(`${base}/v1/transform`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload('7', 'integer')) });
  assert.deepEqual((await response.json()).data, [{ result: 7 }]);
  const large = await fetch(`${base}/v1/transform`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: ' '.repeat(32769) });
  assert.equal(large.status, 413);
});
