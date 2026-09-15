const escapeHtml = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const jsonExample = value => escapeHtml(JSON.stringify(value, null, 2));
const csvRequest = {
  format: 'csv', data: 'sku,name,stock,active\nA1,"Tea, green",7,true\nB2,Coffee,0,false\n',
  schema: [
    { source: 'sku', target: 'id', type: 'string' }, { source: 'name', target: 'name', type: 'string' },
    { source: 'stock', target: 'quantity', type: 'integer' }, { source: 'active', target: 'available', type: 'boolean' },
  ],
};
const jsonRequest = {
  format: 'json',
  data: [{ reference: 101, amount: ' 12.50 ', settled: 'false', note: null }, { reference: 102, amount: 0, settled: true }],
  schema: [
    { source: 'reference', target: 'id', type: 'string' },
    { source: 'amount', target: 'amount', type: 'number', trim: true },
    { source: 'settled', target: 'settled', type: 'boolean' },
    { source: 'note', target: 'note', type: 'string', required: false, nullable: true },
  ],
};
const csvResponse = { ok: true, data: [{ id: 'A1', name: 'Tea, green', quantity: 7, available: true }, { id: 'B2', name: 'Coffee', quantity: 0, available: false }], summary: { inputRows: 2, outputRows: 2, mappedFields: 4, convertedCells: 4 } };
const jsonResponse = { ok: true, data: [{ id: '101', amount: 12.5, settled: false, note: null }, { id: '102', amount: 0, settled: true }], summary: { inputRows: 2, outputRows: 2, mappedFields: 4, convertedCells: 4 } };
const errorResponse = { ok: false, error: { code: 'VALIDATION_FAILED', message: 'Some fields could not be converted. No records were returned.', details: { totalErrors: 1, truncated: false, fields: [{ row: 0, source: 'stock', target: 'quantity', expected: 'integer', code: 'TYPE_MISMATCH' }] } } };
const header = active => `<header class="site-header"><a class="wordmark" href="/" aria-label="SchemaBridge home">Schema<span>Bridge</span></a><nav aria-label="Main navigation"><a href="/">Try the example</a><a href="/docs"${active === 'docs' ? ' aria-current="page"' : ''}>API guide</a><a href="/status"${active === 'status' ? ' aria-current="page"' : ''}>Service status</a></nav></header>`;
const footer = `<footer><p>SchemaBridge · Small tables. Explicit rules.</p><nav aria-label="Technical resources"><a href="/openapi.json" download="schemabridge-openapi.json">Download raw OpenAPI JSON</a><a href="/health" download="schemabridge-health.json">Download raw health JSON</a><a href="https://github.com/wiaikit/fenix-schemabridge" rel="noreferrer">Source code on GitHub</a></nav></footer>`;

export const docsHtml = String.raw`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="A practical guide to SchemaBridge CSV and JSON field mapping, request examples, types, limits and errors."><title>SchemaBridge · API guide</title><link rel="stylesheet" href="/assets/docs.css"></head>
<body><a class="skip-link" href="#main">Skip to the guide</a><div class="page">${header('docs')}
<main id="main" tabindex="-1"><section id="overview" class="intro"><p class="eyebrow">API guide</p><h1>Map your fields.<br>Check your types.</h1><p class="lead">Send a small CSV or JSON table with explicit mapping rules. SchemaBridge returns JSON with the names and types you requested, or an error that points to what needs fixing.</p></section>
<nav class="contents" aria-label="On this page"><a href="#request">Send a request</a><a href="#csv">CSV example</a><a href="#json">JSON example</a><a href="#mapping">Mapping rules</a><a href="#limits">Limits</a><a href="#errors">Errors</a></nav>

<section id="request" class="doc-section"><h2>Send a request</h2><p>Use <code>POST /v1/transform</code> with <code>Content-Type: application/json</code>. Both formats use a JSON envelope with exactly three properties:</p>
<dl class="terms"><dt><code>format</code></dt><dd><code>"csv"</code> for a CSV string, or <code>"json"</code> for an array of flat objects.</dd><dt><code>data</code></dt><dd>The input table. CSV text goes inside this property, not directly in the HTTP body.</dd><dt><code>schema</code></dt><dd>An array of 1 to 20 mappings, each containing <code>source</code>, <code>target</code> and <code>type</code>.</dd></dl>
<p>No account or API key is required by this endpoint. Use synthetic, non-sensitive data for this public demo. Compressed request bodies are not supported.</p>
<p>Save either full request below as <code>request.json</code>, then run:</p><pre><code>curl -X POST https://schemabridge.wiaikit.com/v1/transform \
  -H 'Content-Type: application/json' \
  --data-binary @request.json</code></pre><p class="note">This command uses a POSIX shell. On Windows, use <code>curl.exe</code> and put the command on one line.</p></section>

<section id="csv" class="doc-section"><h2>CSV example</h2><p>The header names the source fields. This request renames <code>stock</code> to <code>quantity</code> and converts its text value to an integer.</p><h3>Full request</h3><pre id="csv-request-example"><code>${jsonExample(csvRequest)}</code></pre><h3>Expected response · HTTP 200</h3><pre id="csv-response-example"><code>${jsonExample(csvResponse)}</code></pre><p>CSV uses commas, unique headers and LF or CRLF line endings. Quoted cells may contain commas or newlines; escape a quote by doubling it. Every record must have the same number of cells as the header. An empty cell is an empty string, never an implicit null.</p></section>

<section id="json" class="doc-section"><h2>JSON example</h2><p>JSON input is an array of flat objects. This example also trims a numeric string, preserves an allowed null and omits an optional missing field.</p><h3>Full request</h3><pre id="json-request-example"><code>${jsonExample(jsonRequest)}</code></pre><h3>Expected response · HTTP 200</h3><pre id="json-response-example"><code>${jsonExample(jsonResponse)}</code></pre><p>The second record has no <code>note</code>, so its output has no <code>note</code> either. Arrays or objects inside cells are rejected; cells may contain strings, finite numbers, booleans or null.</p></section>

<section id="mapping" class="doc-section"><h2>Mapping rules</h2><p><code>source</code> and <code>target</code> are literal top-level field names, not paths. Output target names must be unique. Unmapped input fields are omitted from the result after structural validation. Input row order is preserved. JSON object property order is not part of the contract.</p>
<div class="table-wrap" role="region" aria-label="Supported types" tabindex="0"><table><caption>Supported target types</caption><thead><tr><th scope="col">Type</th><th scope="col">Accepted values</th><th scope="col">Examples that fail</th></tr></thead><tbody>
<tr><th scope="row"><code>string</code></th><td>A string, number or boolean converted to text.</td><td>Nested objects or arrays.</td></tr>
<tr><th scope="row"><code>integer</code></th><td>A parsed safe integer, or a strict decimal integer string. Range: −9,007,199,254,740,991 to 9,007,199,254,740,991.</td><td><code>"7.0"</code>, <code>"1e2"</code>, <code>"+7"</code>, <code>"07"</code>.</td></tr>
<tr><th scope="row"><code>number</code></th><td>A finite number, or a strict numeric string using a decimal point and optional exponent, such as <code>"12.5"</code> or <code>"1e2"</code>.</td><td><code>"12,5"</code>, <code>"+7"</code>, <code>"07"</code>, infinity.</td></tr>
<tr><th scope="row"><code>boolean</code></th><td>A boolean, or exactly <code>"true"</code> / <code>"false"</code>.</td><td><code>1</code>, <code>"yes"</code>, <code>"TRUE"</code>.</td></tr>
</tbody></table></div>
<h3>Optional mapping properties</h3><dl class="terms"><dt><code>required</code></dt><dd>Default <code>true</code>. Set to <code>false</code> to omit a missing field from the output instead of returning an error.</dd><dt><code>nullable</code></dt><dd>Default <code>false</code>. Set to <code>true</code> to preserve an explicit JSON null. This does not make a missing required field optional or turn an empty string into null.</dd><dt><code>trim</code></dt><dd>Default <code>false</code>. Set to <code>true</code> to trim a string before conversion. Otherwise spaces remain significant.</dd></dl>
<p>Unknown request or mapping properties are rejected. Field names must be non-empty, at most 64 UTF-16 code units, and cannot be <code>__proto__</code>, <code>prototype</code> or <code>constructor</code>.</p>
<h3>Numeric precision</h3><p>JSON numeric tokens are parsed as JavaScript IEEE-754 numbers before validation and may already be rounded. For example, the numeric token <code>1.0000000000000001</code> is parsed as <code>1</code>. Use string input when the original digits must be validated. A <code>number</code> conversion still produces an IEEE-754 number; this is not an exact-decimal arithmetic service.</p>
<h3>Read the summary</h3><p><code>inputRows</code> and <code>outputRows</code> count records; <code>mappedFields</code> counts schema mappings. <code>convertedCells</code> counts values changed by trimming or conversion after parsing. Renaming alone does not count as a changed cell.</p></section>

<section id="limits" class="doc-section"><h2>Limits</h2><ul class="plain-list"><li><strong>32 KiB (32,768 bytes)</strong> for the whole UTF-8 JSON request, including its schema.</li><li><strong>100 data records</strong>; the CSV header is separate.</li><li><strong>20 mappings</strong> and at most 20 fields per input record or CSV row.</li><li><strong>64 UTF-16 code units</strong> per field name; <strong>2,048</strong> per string cell.</li><li><strong>64 KiB (65,536 bytes)</strong> for the serialized response. The transformed data has a 65,280-byte budget to reserve 256 bytes for the envelope.</li><li><strong>40 field-error details</strong> at most, with the total count and a truncation flag.</li></ul><p>These are request and response bounds, not a latency or availability guarantee.</p></section>

<section id="errors" class="doc-section"><h2>Errors that tell you where to look</h2><p>Conversion is all-or-nothing: if any field fails, no partial output is returned. For example, replacing the first CSV record's stock value with <code>seven</code> produces:</p><pre id="error-response-example"><code>${jsonExample(errorResponse)}</code></pre><p><code>row</code> is a zero-based data-record index, not a physical CSV line number. Field-error details include names and expected types, not submitted cell values.</p>
<div class="table-wrap" role="region" aria-label="HTTP errors" tabindex="0"><table><caption>HTTP status and next step</caption><thead><tr><th scope="col">Status</th><th scope="col">Meaning</th><th scope="col">What to do</th></tr></thead><tbody>
<tr><th scope="row">400</th><td>Invalid JSON, CSV, schema or record structure.</td><td>Check the request format, headers, field names and options.</td></tr><tr><th scope="row">413</th><td>A request, row, field, cell or output limit was exceeded.</td><td>Send a smaller table or shorter cells.</td></tr><tr><th scope="row">415</th><td>Unsupported media type or content encoding.</td><td>Send uncompressed UTF-8 JSON with <code>Content-Type: application/json</code>.</td></tr><tr><th scope="row">422</th><td>A required field is missing, null is disallowed or a value has the wrong type.</td><td>Use <code>error.details.fields</code> to fix the records or mapping.</td></tr><tr><th scope="row">404 / 405</th><td>Unknown route or unsupported method.</td><td>Check the path; transforms require POST. A 405 response includes <code>Allow</code>.</td></tr><tr><th scope="row">500</th><td>Unexpected processing failure.</td><td>Retry later; do not treat this as valid output.</td></tr><tr><th scope="row">503</th><td>Health or deployment proof has no valid configured commit or slug.</td><td>Check <a href="/status">service status</a>; this is deployment configuration.</td></tr>
</tbody></table></div><p>Errors include <code>ok: false</code>, an <code>error.code</code> and an <code>error.message</code>; <code>error.details</code> is optional.</p></section>
<section id="openapi" class="doc-section"><h2>OpenAPI specification</h2><p>The machine-readable specification describes request fields and response shapes for API tools. <a href="/openapi.json" download="schemabridge-openapi.json">Download raw OpenAPI JSON</a>. For a readable introduction, use the examples above.</p></section>
</main>${footer}</div></body></html>`;

export const statusHtml = `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="Check the current SchemaBridge API health response and configured source commit."><title>SchemaBridge · Service status</title><link rel="stylesheet" href="/assets/docs.css"><script src="/assets/status.js" defer></script></head>
<body><a class="skip-link" href="#main">Skip to service status</a><div class="page">${header('status')}<main id="main" tabindex="-1"><section class="intro"><p class="eyebrow">Service status</p><h1>Check the API.</h1><p class="lead">This page reads the live health endpoint. Refresh to check again; a previous successful response does not guarantee future availability.</p></section>
<section class="status-box" aria-labelledby="status-heading"><h2 id="status-heading">Current check</h2><p id="health-status" class="health-status" role="status" aria-live="polite" aria-atomic="true">Not checked yet.</p><p id="health-explanation">No health result has been received.</p><dl class="terms status-values"><dt>Configured source commit</dt><dd><code id="health-commit">Not available</code></dd><dt>Last check completed</dt><dd id="health-checked">Not checked yet</dd></dl><button id="refresh-status" type="button">Refresh</button><details id="health-details" hidden><summary>View the actual JSON response</summary><pre id="health-json"></pre></details><noscript><p>JavaScript is needed for this live check. You can <a href="/health" download="schemabridge-health.json">download raw health JSON</a> directly.</p></noscript></section>
<p class="status-note">The commit is a value configured by the deployment operator. It is not independent proof of which code the host built. This check does not run a transformation or measure uptime.</p><p><a href="/">Try a real CSV transformation</a> · <a href="/docs">Read the API guide</a></p></main>${footer}</div></body></html>`;

export const docsCss = `@font-face{font-family:"Instrument Sans";src:url("/assets/fonts/instrument-sans-latin.woff2") format("woff2");font-style:normal;font-weight:400 700;font-display:swap}
@font-face{font-family:"Instrument Serif";src:url("/assets/fonts/instrument-serif-latin.woff2") format("woff2");font-style:normal;font-weight:400;font-display:swap}

:root{color-scheme:light;--ink:#202824;--muted:#58635b;--teal:#314a3b;--line:#ccd3ca;--paper:#f3f6f2;--tint:#e8ede5;font-family:"Instrument Sans",system-ui,sans-serif;color:var(--ink);background:var(--paper);font-synthesis:none}
*{box-sizing:border-box}body{margin:0;font-size:16px;line-height:1.7}a{color:var(--teal);text-underline-offset:4px}a:hover{color:#064b45}button{font:inherit;cursor:pointer}a:focus-visible,button:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:3px solid var(--teal);outline-offset:4px}[hidden]{display:none!important}.page{width:min(1080px,100%);padding:0 32px;margin:auto}.skip-link{position:absolute;top:12px;left:16px;padding:10px 16px;background:#fff;transform:translateY(-160%);z-index:2}.skip-link:focus{transform:none}.site-header{min-height:80px;display:flex;align-items:center;justify-content:space-between;gap:24px;border-bottom:1px solid var(--line)}.wordmark{font-size:23px;font-weight:750;letter-spacing:-.8px;color:var(--ink);text-decoration:none;white-space:nowrap}.wordmark span{color:var(--teal)}nav{display:flex;gap:12px 24px;flex-wrap:wrap}.site-header nav{font-size:14px}.site-header nav a{padding:10px 0}nav [aria-current="page"]{font-weight:700;text-decoration-thickness:2px}.intro{max-width:800px;padding:48px 0 28px}.eyebrow{margin:0 0 10px;font-size:14px;font-weight:650;color:var(--teal)}h1{font-family:"Instrument Serif",Georgia,serif;font-size:clamp(46px,6vw,72px);line-height:1.02;letter-spacing:-1px;font-weight:400;margin:0 0 20px}h2{font-size:25px;line-height:1.3;letter-spacing:-.5px;margin:0 0 16px}h3{font-size:17px;margin:26px 0 10px}p{margin:0 0 16px}.lead{font-size:18px;color:var(--muted);margin:0}.contents{padding:18px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);font-size:14px}.doc-section{padding:36px 0;border-bottom:1px solid var(--line);scroll-margin-top:20px}.doc-section p{max-width:820px}.terms{display:grid;grid-template-columns:180px minmax(0,1fr);column-gap:24px;row-gap:12px;margin:20px 0}.terms dt{font-weight:650}.terms dd{margin:0;color:var(--muted)}code,pre{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}code{font-size:.86em;overflow-wrap:anywhere}pre{max-width:100%;overflow:auto;padding:20px;border:1px solid var(--line);border-radius:8px;background:#fff;line-height:1.65;font-size:13px;margin:12px 0 20px;tab-size:2}pre code{font-size:inherit;overflow-wrap:normal;white-space:pre}.note,.status-note{font-size:14px;color:var(--muted)}.table-wrap{overflow:auto;margin:18px 0;border:1px solid var(--line);border-radius:8px;background:#fff}table{border-collapse:collapse;width:100%;min-width:580px;text-align:left;font-size:14px}caption{padding:12px 16px;text-align:left;font-weight:650}th,td{padding:14px 16px;border-top:1px solid var(--line);vertical-align:top}thead{background:var(--tint)}th{font-weight:650}.plain-list{padding-left:22px;margin:0 0 16px}.plain-list li{margin-bottom:10px}.status-box{max-width:780px;padding:28px;border:1px solid var(--line);border-radius:12px;background:#fff;margin:0 0 22px}.health-status{font-size:24px;font-weight:650;margin-bottom:8px}.health-status[data-state="success"]{color:var(--teal)}.health-status[data-state="error"]{color:#922d26}.status-values{border-top:1px solid var(--line);padding-top:20px}.status-values dd{overflow-wrap:anywhere}button{min-height:46px;padding:10px 20px;background:#202824;border:1px solid #202824;border-radius:999px;color:#fff;font-weight:600}button:hover:enabled{background:#3b493f}button:disabled{opacity:.65;cursor:wait}details{margin-top:18px}summary{cursor:pointer;color:var(--teal);font-weight:600;padding:6px 0}#health-json{max-height:300px;white-space:pre-wrap;overflow-wrap:anywhere}.status-note{max-width:780px}footer{padding:26px 0 30px;margin-top:38px;border-top:1px solid var(--line);font-size:13px;color:var(--muted)}footer p{margin-bottom:12px}footer nav a{padding:5px 0}
@media(max-width:700px){.page{padding:0 20px}.site-header{align-items:flex-start;flex-direction:column;gap:4px;padding:20px 0 12px}.site-header nav{gap:4px 20px}.intro{padding-top:32px}.lead{font-size:16px}.terms{grid-template-columns:1fr;row-gap:4px}.terms dd{margin-bottom:12px}.status-box{padding:22px}pre{padding:14px;font-size:12px}.doc-section{padding:28px 0}.contents{gap:8px 20px}}
@media(max-width:400px){.page{padding:0 16px}.site-header nav{font-size:13px;gap:4px 14px}.status-box{padding:18px}h1{font-size:36px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
`;

export const statusJs = String.raw`(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const button = byId('refresh-status'), label = byId('health-status');
  const explanation = byId('health-explanation'), commit = byId('health-commit');
  const checked = byId('health-checked'), details = byId('health-details'), raw = byId('health-json');
  let pending = false;
  function showError(title, message) { label.textContent = title; label.dataset.state = 'error'; explanation.textContent = message; }
  async function readJson(response) {
    if (!response.headers.get('content-type')?.toLowerCase().includes('application/json') || !response.body) throw new Error('unexpected');
    const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', {fatal:true});
    let text = '', bytes = 0;
    try {
      for (;;) {
        const {value,done} = await reader.read(); if (done) break;
        bytes += value.byteLength;
        if (bytes > 4096) { await reader.cancel(); throw new Error('unexpected'); }
        text += decoder.decode(value, {stream:true});
      }
      return JSON.parse(text + decoder.decode());
    } finally { reader.releaseLock(); }
  }
  async function refresh() {
    if (pending) return;
    pending = true; button.disabled = true; button.textContent = 'Checking…';
    label.textContent = 'Checking the API…'; label.dataset.state = 'pending';
    explanation.textContent = 'Waiting for a new response from /health.';
    commit.textContent = 'Not available'; checked.textContent = 'Check in progress';
    details.hidden = true; details.open = false; raw.textContent = '';
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('/health', {method:'GET',headers:{Accept:'application/json'},credentials:'omit',cache:'no-store',redirect:'error',signal:controller.signal});
      const data = await readJson(response);
      details.hidden = false; raw.textContent = JSON.stringify(data, null, 2);
      if (response.status === 200 && data && data.status === 'ok' && typeof data.commit === 'string' && /^[a-fA-F0-9]{40}$/.test(data.commit) && !/^0{40}$/.test(data.commit)) {
        label.textContent = 'API responded successfully'; label.dataset.state = 'success';
        explanation.textContent = 'The live health endpoint returned HTTP 200 and a configured source commit.';
        commit.textContent = data.commit;
      } else if (response.status === 503 && data?.error?.code === 'DEPLOYMENT_UNVERIFIED') {
        showError('Deployment is not verified', 'The service has no valid deployment metadata configured. No healthy status is claimed.');
      } else if (!response.ok) {
        showError('The health check failed', 'The endpoint returned HTTP ' + response.status + '. Try Refresh later.');
      } else showError('Unexpected health response', 'The response did not match the health format. No healthy status is claimed.');
    } catch (error) {
      if (controller.signal.aborted) showError('The check timed out', 'No complete health response arrived within 10 seconds. Check your connection and try Refresh.');
      else if (error.message === 'unexpected' || error instanceof SyntaxError) showError('Unexpected health response', 'A valid JSON health response could not be read. Try Refresh later.');
      else showError('Could not reach the service', 'A network connection could not be completed. Check your connection and try Refresh.');
    } finally {
      clearTimeout(timer); checked.textContent = new Date().toISOString() + ' (your browser clock)';
      pending = false; button.disabled = false; button.textContent = 'Refresh';
    }
  }
  button.addEventListener('click', refresh);
  refresh();
})();`;
