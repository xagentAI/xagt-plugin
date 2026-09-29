export const homepageHtml = `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Rename fields and check data types in small CSV or JSON tables. Try SchemaBridge with a simple live example.">
  <title>SchemaBridge · Clear data from CSV and JSON</title>
  <link rel="preload" href="/assets/fonts/instrument-serif-latin.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/instrument-serif-italic-latin.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="/assets/fonts/instrument-sans-latin.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="stylesheet" href="/assets/app.css">
  <script src="/assets/app.js" defer></script>
</head>
<body>
  <a class="skip-link" href="#demo">Skip to the example</a>
  <div class="page">
    <header class="site-header">
      <a class="wordmark" href="/" aria-label="SchemaBridge">Schema<span>Bridge</span></a>
      <nav class="site-nav" aria-label="Main navigation">
        <a href="#demo">Example</a>
        <a href="/docs">API guide</a>
        <a href="https://github.com/wiaikit/fenix-schemabridge" rel="noreferrer">Source</a>
      </nav>
    </header>
    <main>
      <section class="intro" aria-labelledby="page-title">
        <div class="intro-copy">
          <p class="intro-label">Small tables. Explicit rules.</p>
          <h1 id="page-title">Give your data <span>a clear structure.</span></h1>
          <p class="lead">Rename fields. Validate types. Turn small CSV or JSON tables into data that follows your schema.</p>
          <div class="hero-actions">
            <a class="primary-button hero-button" href="#demo">Try the live example <span aria-hidden="true">→</span></a>
            <a class="guide-link" href="/docs">Read the API guide</a>
          </div>
        </div>
        <figure class="hero-art">
          <img src="/assets/schema-sculpture.png" width="1536" height="1024" alt="A pale sculptural bridge guides loose green forms into an ordered grid." fetchpriority="high" decoding="async">
          <figcaption>From loose records to a defined schema.</figcaption>
        </figure>
      </section>

      <section id="demo" class="demo" aria-labelledby="demo-title" tabindex="-1">
        <div class="demo-heading">
          <h2 id="demo-title">A little clarity, in practice.</h2>
          <p>Edit the source values and send them to the API. Results appear only after the server responds.</p>
        </div>
        <form id="demo-form">
          <div class="panels">
            <section class="input-panel" aria-labelledby="input-title">
              <div class="panel-heading"><h3 id="input-title">Source data</h3><span class="format-label">CSV</span></div>
              <label for="csv-input">A header and two product records</label>
              <textarea id="csv-input" name="csv" rows="7" maxlength="32768" spellcheck="false" autocapitalize="off" autocomplete="off" aria-describedby="input-help limits">sku,name,stock,active
A1,"Tea, green",7,true
B2,Coffee,0,false</textarea>
              <p id="input-help" class="field-help">You can edit this. Replace 7 with seven to see an explanatory validation error.</p>
              <div class="actions">
                <button id="submit-button" class="primary-button" type="submit">Transform example</button>
                <button id="reset-button" class="reset-button" type="button">Reset</button>
              </div>
            </section>
            <section id="result-panel" class="result-panel" aria-labelledby="result-title" aria-busy="false">
              <div class="panel-heading"><h3 id="result-title">Result</h3><span class="format-label">Fields and types</span></div>
              <p id="status" class="status" role="status" aria-live="polite" aria-atomic="true">Nothing has been sent yet. Select “Transform example”.</p>
              <ul id="field-errors" class="field-errors" hidden></ul>
              <div id="empty-result" class="empty-result"><p>Your table of validated values will appear here.</p></div>
              <div id="table-container" class="table-container" role="region" aria-label="Transformed data" tabindex="0" hidden></div>
              <details id="response-details" class="response-details" hidden>
                <summary>View the JSON API response</summary>
                <pre id="response-json"></pre>
              </details>
            </section>
          </div>
        </form>
        <div class="rules">
          <p class="rules-title">This example uses a fixed schema</p>
          <ul class="mapping-list" aria-label="Transformation rules">
            <li><code>sku → id</code><span>text</span></li>
            <li><code>name → name</code><span>text</span></li>
            <li><code>stock → quantity</code><span>integer</span></li>
            <li><code>active → available</code><span>true or false</span></li>
          </ul>
          <p class="field-help">Keep these four headers. The API also accepts custom schemas and JSON; this page demonstrates one simple workflow.</p>
        </div>
        <p id="limits" class="limits">Up to 100 data rows and 32 KiB for the entire request, including the schema. Use only synthetic data with no personal or confidential information.</p>
        <noscript><p class="noscript-note">JavaScript is needed for the live example; API documentation is linked below.</p></noscript>
      </section>
    </main>
    <footer>
      <details class="developer-details">
        <summary>For developers</summary>
        <p>Read the API guide, check service status, or browse the source code.</p>
        <nav aria-label="API documentation">
          <a href="/docs#overview">API overview</a>
          <a href="/status">Service health</a>
          <a href="/docs">OpenAPI</a>
          <a href="https://github.com/wiaikit/fenix-schemabridge" rel="noreferrer">Source code</a>
        </nav>
      </details>
      <p class="footer-note">SchemaBridge · Transform data using rules you define.</p>
    </footer>
  </div>
</body>
</html>`;

export const homepageCss = `
@font-face{font-family:"Instrument Sans";src:url('/assets/fonts/instrument-sans-latin.woff2') format('woff2');font-style:normal;font-weight:400 700;font-display:swap}
@font-face{font-family:"Instrument Serif";src:url('/assets/fonts/instrument-serif-latin.woff2') format('woff2');font-style:normal;font-weight:400;font-display:swap}
@font-face{font-family:"Instrument Serif";src:url('/assets/fonts/instrument-serif-italic-latin.woff2') format('woff2');font-style:italic;font-weight:400;font-display:swap}
:root{color-scheme:light;--ink:#1c2521;--muted:#56635b;--accent:#334e3e;--line:#cbd3c9;--paper:#f3f6f2;--surface:#fcfdf9;--tint:#e7ede4;--error:#9f352d;font-family:"Instrument Sans","Segoe UI",system-ui,sans-serif;color:var(--ink);background:var(--paper);font-synthesis:none}
*{box-sizing:border-box}
html{scroll-behavior:smooth}
body{margin:0;font-size:16px;line-height:1.6;-webkit-font-smoothing:antialiased;background-image:linear-gradient(rgba(28,37,33,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(28,37,33,.025) 1px,transparent 1px);background-size:72px 72px}
button,textarea{font:inherit}
button,a,summary{-webkit-tap-highlight-color:transparent}
button{cursor:pointer}
a{color:var(--ink);text-underline-offset:5px;text-decoration-thickness:1px}
a:hover{color:var(--accent)}
button:focus-visible,a:focus-visible,textarea:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:3px solid var(--accent);outline-offset:5px}
[hidden]{display:none!important}
.page{width:min(1400px,100%);margin:auto;padding:0 56px}
.skip-link{position:absolute;top:12px;left:16px;z-index:3;padding:10px 16px;border:1px solid var(--ink);border-radius:5px;background:var(--surface);transform:translateY(-160%)}
.skip-link:focus{transform:none}
.site-header{min-height:88px;display:flex;align-items:center;justify-content:space-between;gap:28px;border-bottom:1px solid var(--line)}
.wordmark{text-decoration:none;font-size:24px;letter-spacing:-1.2px;font-weight:650;color:var(--ink);white-space:nowrap}
.wordmark span{color:var(--accent);font-weight:450}
.site-nav{display:flex;align-items:center;gap:34px}
.site-nav a{display:inline-flex;align-items:center;min-height:44px;font-size:13px;font-weight:550;text-decoration:none;color:var(--ink)}
.site-nav a:hover{text-decoration:underline;text-decoration-color:var(--accent)}
.intro{display:grid;grid-template-columns:minmax(0,44fr) minmax(0,56fr);align-items:center;gap:0;min-height:584px;padding:54px 0 48px;border-bottom:1px solid var(--line)}
.intro-copy{position:relative;z-index:1;min-width:0}
.intro-label{display:flex;align-items:center;gap:12px;margin:0 0 24px;color:var(--muted);font-size:12px;font-weight:500;letter-spacing:.02em}
.intro-label::before{content:"";display:block;width:25px;height:1px;background:#7e8d7f;flex:none}
h1,h2,h3,p{margin-top:0}
h1{margin-bottom:26px;font-family:"Instrument Serif",Georgia,serif;font-size:clamp(70px,6.65vw,93px);font-weight:400;letter-spacing:-2.4px;line-height:1.05}
h1 span{display:block;padding-bottom:5px;font-style:italic;line-height:1.1}
.lead{max-width:395px;margin:0;font-size:18px;line-height:1.75;color:var(--muted);letter-spacing:-.12px}
.hero-actions{display:flex;align-items:center;flex-wrap:wrap;gap:16px 25px;margin-top:31px}
.hero-button{display:inline-flex;align-items:center;justify-content:center;gap:22px;min-height:53px;text-decoration:none;white-space:nowrap}
.hero-button span{display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;flex:none;border:1px solid #80877f;border-radius:50%;font-size:16px;font-weight:400;line-height:1}
.guide-link{display:inline-flex;align-items:center;min-height:44px;font-size:13px;font-weight:500;color:var(--ink);text-decoration-color:#919e91}
.hero-art{min-width:0;margin:0 -30px 0 -12px;align-self:center}
.hero-art img{display:block;width:100%;height:auto;aspect-ratio:3/2;object-fit:contain}
.hero-art figcaption{margin:10px 30px 0 0;text-align:right;font-size:11px;letter-spacing:.015em;color:var(--muted)}
.demo{margin:60px 0 50px;scroll-margin-top:24px}
.demo-heading{margin-bottom:29px}
h2{margin-bottom:10px;font-family:"Instrument Serif",Georgia,serif;font-size:42px;font-weight:400;letter-spacing:-.75px;line-height:1.15}
.demo-heading p{max-width:715px;margin-bottom:0;color:var(--muted);font-size:13px;line-height:1.8}
.panels{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);border:1px solid var(--line);border-top-color:#7f8b7f;border-radius:8px;background:var(--surface);box-shadow:0 3px 0 rgba(32,46,33,.025)}
.input-panel,.result-panel{min-width:0;padding:29px}
.result-panel{border-left:1px solid var(--line);border-radius:0 8px 8px 0;background:#edf2e9}
.panel-heading{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin-bottom:22px;padding-bottom:18px;border-bottom:1px solid var(--line)}
h3{margin:0;font-size:17px;line-height:1.4;font-weight:550;letter-spacing:-.35px}
.format-label{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:10px;color:var(--muted);white-space:nowrap}
label{display:block;font-size:12px;font-weight:500;margin-bottom:10px;color:var(--muted)}
textarea{display:block;width:100%;min-height:173px;max-height:480px;resize:vertical;border:1px solid #7b8a7c;border-radius:5px;padding:15px 17px;background:#f8faf6;color:var(--ink);font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:13px;line-height:1.85;white-space:pre;overflow:auto;caret-color:var(--ink)}
textarea[aria-invalid="true"]{border-color:var(--error)}
.field-help{font-size:12px;line-height:1.8;color:var(--muted);margin:12px 0 0}
.actions{display:flex;align-items:center;flex-wrap:wrap;gap:12px;margin-top:23px}
.primary-button,.reset-button{min-height:46px;max-width:100%;border-radius:999px;padding:12px 20px;font-size:13px;font-weight:550;line-height:1.5;transition:background-color .15s ease,border-color .15s ease,color .15s ease}
.primary-button{border:1px solid var(--ink);background:var(--ink);color:#fafbf5}
.primary-button:hover:enabled,a.primary-button:hover{background:#354037;border-color:#354037;color:#fafbf5}
.hero-button{padding:12px 14px 12px 22px;font-size:13px}
.reset-button{border:1px solid transparent;color:var(--ink);background:transparent}
.reset-button:hover:enabled{background:var(--tint);border-color:var(--line)}
button:disabled{cursor:wait;opacity:.65}
textarea:disabled{opacity:.8}
.status{font-size:13px;line-height:1.8;margin-bottom:20px;color:var(--muted);overflow-wrap:anywhere}
.status[data-state="success"]{color:#2f553a;font-weight:600}
.status[data-state="error"]{color:var(--error)}
.status[data-state="pending"]{color:var(--ink);font-weight:600}
.empty-result{display:flex;min-height:173px;align-items:center;justify-content:center;border:1px solid #b7c5b2;border-radius:5px;padding:24px;color:var(--muted);text-align:center;background:#f3f7ef}
.empty-result p{max-width:260px;margin:0;font-size:13px;line-height:1.8}
.table-container{overflow:auto;max-height:352px;border:1px solid #b3c1af;border-radius:5px;background:var(--surface)}
table{width:100%;border-collapse:collapse;text-align:left;font-size:13px}
caption{padding:12px 14px;text-align:left;color:var(--muted);font-size:11px;line-height:1.65}
th,td{padding:12px 14px;border-top:1px solid var(--line);vertical-align:top;max-width:220px;overflow-wrap:anywhere}
th{background:#e4ebde;color:var(--ink);font-size:11px;font-weight:600}
td{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;color:var(--ink)}
.field-errors{padding-left:20px;margin:0 0 18px;font-size:12px;color:var(--error);overflow-wrap:anywhere}
.response-details{margin-top:18px;font-size:12px}
summary{cursor:pointer;color:var(--ink);font-weight:550;min-height:44px;padding:10px 0}
pre{max-height:300px;overflow:auto;white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;line-height:1.75;padding:16px;background:var(--surface);color:var(--ink);border:1px solid var(--line);border-radius:5px}
.rules{display:grid;grid-template-columns:240px minmax(0,1fr);gap:10px 28px;padding:28px 0 25px;border-bottom:1px solid var(--line)}
.rules-title{font-size:12px;font-weight:500;color:var(--muted);margin:0}
.mapping-list{list-style:none;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:18px;margin:0;padding:0}
.mapping-list li{display:flex;flex-direction:column;gap:5px;font-size:11px;color:var(--muted)}
.rules>.field-help{grid-column:2;margin-top:8px}
code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace;font-size:12px;color:var(--ink)}
.limits{font-size:11px;color:var(--muted);margin:18px 0 0;max-width:920px;line-height:1.85}
.noscript-note{padding:16px;border:1px solid var(--line)}
footer{border-top:1px solid var(--line);padding:24px 0 32px}
.developer-details{font-size:13px}
.developer-details p{max-width:720px;color:var(--muted);margin:8px 0 12px}
.developer-details nav{display:flex;flex-wrap:wrap;gap:10px 28px}
.developer-details nav a{display:inline-flex;align-items:center;min-height:44px;padding:5px 0}
.footer-note{font-size:11px;color:var(--muted);margin:25px 0 0}
@media(max-width:1200px){.page{padding:0 40px}.intro{min-height:550px;padding:45px 0 40px}h1{font-size:clamp(65px,7.3vw,84px);letter-spacing:-2px}.hero-art{margin-right:-20px}.lead{max-width:345px;font-size:15px}.hero-actions{gap:10px 21px}.hero-art figcaption{margin-right:20px}.rules{grid-template-columns:195px minmax(0,1fr);gap:10px 24px}.input-panel,.result-panel{padding:26px}}
@media(max-width:950px){.page{padding:0 28px}.intro{grid-template-columns:minmax(0,46fr) minmax(0,54fr);min-height:510px}h1{font-size:65px;letter-spacing:-1.6px}.intro-label{font-size:11px;gap:10px}.intro-label::before{width:20px}.hero-art{margin-left:-7px;margin-right:-18px}.hero-actions{margin-top:25px}.hero-art figcaption{font-size:10px}.rules{grid-template-columns:1fr;gap:18px}.rules>.field-help{grid-column:1;margin:0}.demo{margin-top:50px}}
@media(max-width:760px){.page{padding:0 24px}.site-header{min-height:76px;gap:16px}.site-nav{gap:24px}.site-nav a{font-size:12px}.intro{grid-template-columns:1fr;gap:25px;padding:42px 0 32px;min-height:0}.intro-copy{max-width:550px}h1{font-size:clamp(67px,10.5vw,86px);letter-spacing:-2px}.lead{max-width:390px;font-size:16px}.intro-label{font-size:12px;margin-bottom:23px}.hero-actions{margin-top:27px;gap:14px 25px}.hero-art{width:100%;margin:0;justify-self:center}.hero-art figcaption{margin-right:0;font-size:11px;text-align:center}.demo{margin-top:39px}.demo-heading{margin-bottom:26px}h2{font-size:39px}.panels{grid-template-columns:1fr}.input-panel,.result-panel{padding:26px}.result-panel{border-left:0;border-top:1px solid var(--line);border-radius:0 0 8px 8px}.mapping-list{gap:16px}.empty-result{min-height:150px}}
@media(max-width:480px){.page{padding:0 20px}.site-header{flex-wrap:wrap;justify-content:flex-start;gap:0;padding:18px 0 7px}.wordmark{width:100%;font-size:24px}.site-nav{width:100%;justify-content:space-between;gap:18px}.site-nav a{font-size:12px}.intro{padding-top:34px;gap:22px}.intro-label{font-size:11px;margin-bottom:21px}h1{font-size:65px;letter-spacing:-1.7px;margin-bottom:23px}.lead{font-size:15px}.hero-actions{gap:8px 20px;margin-top:26px}.hero-button{white-space:normal}.hero-art figcaption{font-size:10px}.demo{margin-top:33px}.demo-heading{margin-bottom:23px}h2{font-size:35px;max-width:340px}.demo-heading p{font-size:13px}.input-panel,.result-panel{padding:20px}.panel-heading{margin-bottom:20px;padding-bottom:16px;gap:8px}.format-label{font-size:10px}.primary-button{padding:12px 18px}.hero-button{padding:12px 13px 12px 20px}.actions{gap:8px}.mapping-list{grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}.rules{padding-top:24px}.rules-title{font-size:12px}.limits{font-size:11px}.developer-details nav{column-gap:22px}}
@media(max-width:360px){.page{padding:0 16px}h1{font-size:57px;letter-spacing:-1.5px}.intro-label{font-size:10px}.hero-button{width:100%;gap:20px}.input-panel,.result-panel{padding:16px}.actions .primary-button{width:100%}textarea{font-size:12px;padding:12px}.hero-art figcaption{font-size:10px}.panel-heading{gap:6px}h3{font-size:16px}h2{font-size:33px}}
@media(prefers-reduced-motion:reduce){*,*::before,*::after{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
`;

export const homepageJs = String.raw`(() => {
  'use strict';
  const copy = {
    pageTitle: 'SchemaBridge · Clear data from CSV and JSON', skip: 'Skip to the example',
    eyebrow: 'Small tables. Explicit rules.', heading: 'Get your data into the right shape.',
    intro: 'SchemaBridge renames fields and checks types in small CSV or JSON tables. For example, stock becomes quantity, and the text “7” becomes the number 7. Try it with the two products below.',
    demoTitle: 'From CSV to clearly defined fields', demoIntro: 'Edit the source values and send them to the API. Results appear only after the server responds.',
    inputTitle: 'Source data', inputLabel: 'A header and two product records', inputHelp: 'You can edit this. Replace 7 with seven to see an explanatory validation error.',
    submit: 'Transform example', reset: 'Reset', resultTitle: 'Result', typedData: 'Fields and types',
    idle: 'Nothing has been sent yet. Select “Transform example”.', edited: 'The data has changed. Transform it to see an updated result.',
    pending: 'Sending data and checking types…', empty: 'Your table of validated values will appear here.',
    tableRegion: 'Transformed data', tableCaption: 'Values from the API response. Text is quoted; numbers and true/false are not.',
    responseDetails: 'View the JSON API response', schemaTitle: 'This example uses a fixed schema', mappingLabel: 'Transformation rules',
    stringType: 'text', integerType: 'integer', booleanType: 'true or false',
    schemaHelp: 'Keep these four headers. The API also accepts custom schemas and JSON; this page demonstrates one simple workflow.',
    limits: 'Up to 100 data rows and 32 KiB for the entire request, including the schema. Use only synthetic data with no personal or confidential information.',
    developerTitle: 'For developers', developerHelp: 'Call the same API from your application. Request formats and limits are documented in OpenAPI.',
    developerNav: 'API documentation', apiLink: 'API overview', healthLink: 'Service health', sourceLink: 'Source code', footerNote: 'SchemaBridge · Transform data using rules you define.',
    success: (rows, cells) => 'Done. Rows processed: ' + rows + '. Values with a changed type: ' + cells + '.',
    validation: 'Some values do not match the schema. stock needs an integer, and active needs true or false. Fix the data and try again. No partial result is returned.',
    invalidCsv: 'The CSV could not be read. Check commas, quotes and the number of cells in each record.',
    header: 'Keep the header sku,name,stock,active. Column names must be unique.',
    tooLarge: 'The request is too large. Reduce the data: at most 100 rows and 32 KiB including the schema.',
    cellLimit: 'A value is too long or there are too many columns. Shorten the cells and keep the four example columns.',
    timeout: 'The server did not respond within 15 seconds. Check your connection and try again.',
    network: 'The service could not be reached. Check your connection and try again.',
    server: 'The service could not process the request right now. Please try again later.',
    unexpected: 'The service returned an unexpected response. No result is shown; please try again later.',
    emptyInput: 'Add CSV with the header sku,name,stock,active and data records.',
    field: (row, source, type) => 'Record ' + row + ', field ' + source + ': expected ' + type + '.',
    missing: (row, source) => 'Record ' + row + ': required field ' + source + ' is missing.'
  };
  const initialCsv = 'sku,name,stock,active\nA1,"Tea, green",7,true\nB2,Coffee,0,false';
  const schema = [
    {source:'sku',target:'id',type:'string'}, {source:'name',target:'name',type:'string'},
    {source:'stock',target:'quantity',type:'integer'}, {source:'active',target:'available',type:'boolean'}
  ];
  const byId = id => document.getElementById(id);
  const input = byId('csv-input'), submit = byId('submit-button'), reset = byId('reset-button');
  const status = byId('status'), container = byId('table-container'), errors = byId('field-errors');
  let phase = 'idle', responseData = null, errorKey = null;

  function render() {
    const t = copy;
    const pending = phase === 'pending';
    submit.disabled = pending; reset.disabled = pending; input.disabled = pending;
    byId('result-panel').setAttribute('aria-busy', String(pending));
    submit.textContent = pending ? t.pending : t.submit;
    status.dataset.state = phase;
    status.textContent = phase === 'success' ? t.success(responseData.summary.outputRows, responseData.summary.convertedCells)
      : phase === 'error' ? t[errorKey] : t[phase];
    input.setAttribute('aria-invalid', String(phase === 'error' && ['validation','invalidCsv','header','tooLarge','cellLimit','emptyInput'].includes(errorKey)));
    errors.replaceChildren();
    const fields = responseData && responseData.error && responseData.error.details && responseData.error.details.fields;
    if (phase === 'error' && Array.isArray(fields)) fields.slice(0, 4).forEach(field => {
      if (!Number.isInteger(field.row) || field.row < 0 || typeof field.source !== 'string') return;
      const type = {integer:t.integerType,string:t.stringType,boolean:t.booleanType}[field.expected] || field.expected;
      const item = document.createElement('li');
      item.textContent = field.code === 'MISSING_FIELD' ? t.missing(field.row + 1, field.source.slice(0, 64))
        : t.field(field.row + 1, field.source.slice(0, 64), String(type).slice(0, 64));
      errors.append(item);
    });
    errors.hidden = errors.childElementCount === 0;
    byId('empty-result').hidden = phase === 'success';
    container.hidden = phase !== 'success';
    container.replaceChildren();
    if (phase === 'success') {
      const table = document.createElement('table'), caption = document.createElement('caption');
      caption.textContent = t.tableCaption; table.append(caption);
      const head = document.createElement('thead'), heading = document.createElement('tr');
      schema.forEach(field => { const cell = document.createElement('th'); cell.scope = 'col'; cell.textContent = field.target; heading.append(cell); });
      head.append(heading); table.append(head);
      const body = document.createElement('tbody');
      responseData.data.forEach(record => {
        const row = document.createElement('tr');
        schema.forEach(field => { const cell = document.createElement('td'); cell.textContent = JSON.stringify(record[field.target]); row.append(cell); });
        body.append(row);
      });
      table.append(body); container.append(table);
    }
    byId('response-details').hidden = responseData === null;
    byId('response-json').textContent = responseData === null ? '' : JSON.stringify(responseData, null, 2);
  }

  function fail(key, data = null) { phase = 'error'; errorKey = key; responseData = data; render(); }
  function clear(nextPhase) {
    phase = nextPhase; responseData = null; errorKey = null;
    byId('response-details').open = false; render();
  }
  async function readResponse(response) {
    if (!response.headers.get('content-type')?.toLowerCase().includes('application/json') || !response.body) throw new Error('unexpected');
    const reader = response.body.getReader(), decoder = new TextDecoder('utf-8', {fatal:true});
    let text = '', bytes = 0;
    try {
      for (;;) {
        const chunk = await reader.read(); if (chunk.done) break;
        bytes += chunk.value.byteLength;
        if (bytes > 65536) { await reader.cancel(); throw new Error('unexpected'); }
        text += decoder.decode(chunk.value, {stream:true});
      }
      return JSON.parse(text + decoder.decode());
    } finally { reader.releaseLock(); }
  }
  function validSuccess(value) {
    return value && value.ok === true && Array.isArray(value.data) && value.data.length <= 100 &&
      value.summary && Number.isInteger(value.summary.outputRows) && value.summary.outputRows === value.data.length &&
      Number.isInteger(value.summary.convertedCells) && value.summary.convertedCells >= 0 && value.summary.convertedCells <= 400 &&
      value.data.every(row => row && typeof row.id === 'string' && typeof row.name === 'string' &&
        Number.isSafeInteger(row.quantity) && typeof row.available === 'boolean');
  }
  byId('demo-form').addEventListener('submit', async event => {
    event.preventDefault(); if (phase === 'pending') return;
    if (!input.value.trim()) { fail('emptyInput'); return; }
    const body = JSON.stringify({format:'csv',data:input.value,schema});
    if (new TextEncoder().encode(body).byteLength > 32768) { fail('tooLarge'); return; }
    clear('pending');
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/v1/transform', {
        method:'POST', headers:{'Content-Type':'application/json','Accept':'application/json'}, body,
        credentials:'omit', cache:'no-store', redirect:'error', signal:controller.signal
      });
      const data = await readResponse(response);
      if (response.status === 200 && validSuccess(data)) { responseData = data; phase = 'success'; errorKey = null; render(); }
      else if (!response.ok) {
        const code = data && data.error && data.error.code;
        const key = {VALIDATION_FAILED:'validation',INVALID_CSV:'invalidCsv',CSV_COLUMN_COUNT:'invalidCsv',
          INVALID_CSV_HEADER:'header',BODY_LIMIT:'tooLarge',ROW_LIMIT:'tooLarge',CELL_LIMIT:'cellLimit',
          FIELD_LIMIT:'cellLimit',OUTPUT_LIMIT:'tooLarge'}[code];
        fail(key || (response.status >= 500 ? 'server' : 'unexpected'), data);
      } else fail('unexpected', data);
    } catch (error) {
      fail(controller.signal.aborted ? 'timeout' : error.message === 'unexpected' || error instanceof SyntaxError ? 'unexpected' : 'network');
    } finally { clearTimeout(timeout); }
  });
  reset.addEventListener('click', () => { if (phase === 'pending') return; input.value = initialCsv; clear('idle'); input.focus(); });
  input.addEventListener('input', () => { if (phase !== 'edited') clear('edited'); });
  render();
})();`;
