from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .scoring import qualify
from .x402 import decode_payment_payload, encode_payment_required, payment_required_response, verify_and_settle

SLUG = "tamer-powered-site-qualifier"
COMMIT = os.getenv("XAGENT_REVIEW_COMMIT", "local-development")


class SiteQualificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    country_state: str | None = None
    available_mw: float | None = Field(default=None, ge=0)
    power_ready_now: bool | None = None
    energization_rfs_date: str | None = None
    voltage: str | None = None
    utility_interconnection_status: str | None = None
    grid_or_gas_to_power: str | None = None
    power_price_usd_kwh: float | None = Field(default=None, ge=0)
    land_size_acres: float | None = Field(default=None, ge=0)
    lease_sale_jv: str | None = None
    fiber_availability: str | None = None
    water_availability: str | None = None
    gas_availability: str | None = None
    permitting_status: str | None = None
    expansion_capacity_mw: float | None = Field(default=None, ge=0)
    intended_use: str = "both"


app = FastAPI(title="Powered-Site Qualifier API", version="0.1.0", description="Deterministic powered-site qualification for Bitcoin mining and AI/data-center infrastructure.")


LANDING_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="Interactive AI-ready qualification for Bitcoin mining and data-center powered sites.">
  <title>Powered-Site Qualifier</title>
  <style>
    :root { color-scheme: dark; --bg: #08111f; --panel: #101d30; --panel-2: #0c192a; --line: #263b56; --text: #ecf4ff; --muted: #9eb1c9; --accent: #55d6be; --blue: #6aa8ff; --danger: #ff9f9f; }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body { margin: 0; background: radial-gradient(circle at 80% 0, #18375a 0, var(--bg) 42rem); color: var(--text); font: 16px/1.55 system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    a { color: #b9d2ff; }
    main, nav > div { width: min(1120px, calc(100% - 2rem)); margin: 0 auto; }
    nav { position: sticky; top: 0; z-index: 5; border-bottom: 1px solid #1a2d45; background: rgba(8, 17, 31, .9); backdrop-filter: blur(12px); }
    nav > div { display: flex; align-items: center; justify-content: space-between; gap: 1rem; min-height: 4rem; }
    .brand { color: var(--text); font-weight: 800; text-decoration: none; white-space: nowrap; }
    .nav-links { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: .85rem; font-size: .9rem; }
    .nav-links a { color: var(--muted); text-decoration: none; }
    .nav-links a:hover, .nav-links a:focus { color: var(--accent); }
    main { padding: 2.5rem 0 4rem; }
    .hero { padding: 1.5rem 0 2rem; }
    .eyebrow { color: var(--accent); font-size: .78rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }
    h1 { margin: .5rem 0 1rem; font-size: clamp(2.3rem, 7vw, 4.8rem); line-height: 1.03; letter-spacing: -.045em; }
    h2 { margin: 0 0 .8rem; font-size: 1.2rem; }
    h3 { margin: 0 0 .45rem; font-size: 1rem; }
    .subtitle { max-width: 720px; margin: 0; color: #d7e5f8; font-size: clamp(1.1rem, 2.2vw, 1.45rem); }
    .description { max-width: 720px; color: var(--muted); }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr)); gap: 1rem; }
    .card { border: 1px solid var(--line); border-radius: 16px; background: color-mix(in srgb, var(--panel) 94%, transparent); padding: 1.25rem; }
    .wide { grid-column: 1 / -1; }
    .actions { display: flex; flex-wrap: wrap; gap: .75rem; margin-top: 1.5rem; }
    button, a.button { border: 1px solid var(--accent); border-radius: 999px; color: #061b1a; background: var(--accent); cursor: pointer; font: inherit; font-weight: 750; padding: .65rem 1rem; text-decoration: none; }
    button.secondary, a.button.secondary { border-color: var(--line); color: var(--text); background: var(--panel); }
    button:disabled { cursor: wait; opacity: .65; }
    .form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
    label { display: grid; gap: .35rem; color: #dceaff; font-size: .9rem; font-weight: 650; }
    input, select, textarea { width: 100%; border: 1px solid #304863; border-radius: 9px; background: #0a1728; color: var(--text); font: inherit; padding: .65rem .7rem; }
    input:focus, select:focus, textarea:focus { border-color: var(--accent); outline: 2px solid rgba(85, 214, 190, .2); }
    textarea { min-height: 6rem; resize: vertical; }
    .help, .muted { color: var(--muted); font-size: .88rem; }
    .status { min-height: 1.6rem; margin: 1rem 0 0; color: var(--muted); }
    .status.success { color: var(--accent); }
    .status.error { color: var(--danger); }
    .results[hidden], .payment-result[hidden] { display: none; }
    .result-top { display: flex; align-items: center; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
    .classification { color: var(--accent); font-size: 1.6rem; font-weight: 850; letter-spacing: .02em; }
    .scores { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin-top: 1rem; }
    .score-card { border: 1px solid var(--line); border-radius: 12px; background: var(--panel-2); padding: 1rem; }
    .score-number { color: var(--blue); font-size: 2rem; font-weight: 850; }
    .bar { height: .55rem; margin-top: .5rem; overflow: hidden; border-radius: 999px; background: #20344c; }
    .bar > i { display: block; height: 100%; border-radius: inherit; background: linear-gradient(90deg, var(--blue), var(--accent)); }
    .result-lists { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin-top: 1rem; }
    .result-lists section { border-top: 1px solid var(--line); padding-top: 1rem; }
    ul { margin: 0; padding-left: 1.2rem; color: var(--muted); }
    li + li { margin-top: .3rem; }
    .endpoint { display: flex; gap: .75rem; align-items: baseline; padding: .45rem 0; border-bottom: 1px solid #1b2d44; }
    .endpoint:last-child { border-bottom: 0; }
    .method { min-width: 3.4rem; color: var(--blue); font: 700 .78rem ui-monospace, SFMono-Regular, Menlo, monospace; }
    code { color: #c4d8ff; font: .92em ui-monospace, SFMono-Regular, Menlo, monospace; overflow-wrap: anywhere; }
    .proof { display: grid; gap: .4rem; color: var(--muted); }
    .proof strong { color: var(--text); }
    .flow { display: grid; justify-items: center; gap: .35rem; margin: .5rem auto 0; color: #cbd9eb; text-align: center; }
    .flow span { width: min(100%, 310px); border: 1px solid var(--line); border-radius: 10px; background: var(--panel-2); padding: .55rem .8rem; }
    .arrow { color: var(--accent); line-height: 1; }
    .note { margin-top: 1.5rem; border-left: 3px solid var(--blue); color: var(--muted); padding: .25rem 0 .25rem 1rem; }
    footer { margin-top: 2rem; color: #7187a3; font-size: .9rem; }
    @media (max-width: 680px) { nav > div { align-items: flex-start; flex-direction: column; padding: .8rem 0; } .nav-links { justify-content: flex-start; gap: .55rem .8rem; } .form-grid, .scores, .result-lists { grid-template-columns: 1fr; } main { padding-top: 1.5rem; } }
  </style>
</head>
<body>
  <nav><div><a class="brand" href="#top">Powered-Site Qualifier</a><div class="nav-links"><a href="#tool">Try Tool</a><a href="#how-it-works">How It Works</a><a href="#x402">x402 Payment</a><a href="#api">API</a><a href="https://github.com/CryptoLeaks/powered-site-qualifier">GitHub</a></div></div></nav>
  <main id="top">
    <section class="hero"><div class="eyebrow">Live infrastructure qualification API</div><h1>Powered-Site Qualifier</h1><p class="subtitle">AI-ready qualification for Bitcoin mining and data-center powered sites.</p><p class="description">Enter powered-site facts and run a real deterministic qualification against the live API. Unknowns stay visible instead of being guessed.</p><div class="actions"><a class="button" href="#tool">Try the tool</a><a class="button secondary" href="/health">Health Check</a></div><div class="grid" style="margin-top: 1.5rem" aria-label="Live service status"><div class="card"><h3>API</h3><div id="api-status" class="status">Checking...</div></div><div class="card"><h3>HTTPS</h3><div id="https-status" class="status">Checking...</div></div><div class="card"><h3>Health</h3><div id="health-status" class="status">Checking...</div></div><div class="card"><h3>x402</h3><div id="x402-status" class="status">Hedera Testnet</div></div><div class="card"><h3>Source</h3><div class="status success">Public</div></div></div></section>

    <section id="tool" class="card"><h2>Powered Site Qualification</h2><p class="help">Use the fictional example for a fast demo, or enter your own non-confidential site information.</p><form id="qualify-form"><div class="form-grid">
      <label>Country / State<input id="country_state" type="text" placeholder="e.g. Oklahoma, USA"></label>
      <label>Intended use<select id="intended_use"><option value="Bitcoin mining">Bitcoin Mining</option><option value="AI data center">AI / Data Center</option><option value="both" selected>Both</option></select></label>
      <label>Available power (MW)<input id="available_mw" type="number" min="0" step="any" placeholder="20"></label>
      <label>Power ready now<select id="power_ready_now"><option value="">Unknown</option><option value="true">Yes</option><option value="false">No</option></select></label>
      <label>RFS / energization date<input id="energization_rfs_date" type="date"></label>
      <label>Power source<select id="grid_or_gas_to_power"><option value="">Unknown</option><option value="grid">Grid</option><option value="gas-to-power">Gas-to-power</option><option value="hydro">Hydro</option><option value="other">Other</option></select></label>
      <label>Power price ($/kWh)<input id="power_price_usd_kwh" type="number" min="0" step="0.001" placeholder="0.055"></label>
      <label>Voltage<input id="voltage" type="text" placeholder="e.g. 138 kV"></label>
      <label>Utility / interconnection status<input id="utility_interconnection_status" type="text" placeholder="e.g. interconnected"></label>
      <label>Land available (acres)<input id="land_size_acres" type="number" min="0" step="any" placeholder="120"></label>
      <label>Deal type<select id="lease_sale_jv"><option value="">Unknown</option><option value="lease">Lease</option><option value="sale">Sale</option><option value="lease / sale / jv">Both</option></select></label>
      <label>Fiber available<select id="fiber_availability"><option value="">Unknown</option><option value="available">Yes</option><option value="unavailable">No</option></select></label>
      <label>Water available<select id="water_availability"><option value="">Unknown</option><option value="available">Yes</option><option value="unavailable">No</option></select></label>
      <label>Gas available<select id="gas_availability"><option value="">Unknown</option><option value="available">Yes</option><option value="unavailable">No</option></select></label>
      <label>Permitting status<input id="permitting_status" type="text" placeholder="e.g. approved"></label>
      <label>Expansion capacity (MW)<input id="expansion_capacity_mw" type="number" min="0" step="any" placeholder="35"></label>
      <label style="grid-column: 1 / -1">Notes / additional information<textarea id="notes" placeholder="Optional context for your own workflow"></textarea><span class="help">Informational only — notes do not affect scoring and are not sent to the API.</span></label>
    </div><div class="actions"><button id="run-button" type="submit">Run Qualification</button><button id="example-button" class="secondary" type="button">Load Example Site</button></div><p id="form-status" class="status" role="status" aria-live="polite"></p></form></section>

    <section id="results" class="card results" hidden aria-live="polite"><div class="result-top"><div><h2>Qualification Result</h2><div id="classification" class="classification"></div></div><div id="result-intended" class="muted"></div></div><div class="scores"><div class="score-card"><h3>Bitcoin Mining Readiness</h3><div><span id="bitcoin-score" class="score-number">—</span> / 100</div><div class="bar"><i id="bitcoin-bar" style="width: 0%"></i></div></div><div class="score-card"><h3>AI / Data Center Readiness</h3><div><span id="ai-score" class="score-number">—</span> / 100</div><div class="bar"><i id="ai-bar" style="width: 0%"></i></div></div></div><div class="result-lists"><section><h3>Positives</h3><ul id="positives"></ul></section><section><h3>Blockers</h3><ul id="blockers"></ul></section><section><h3>Missing information</h3><ul id="missing"></ul></section><section><h3>Next questions</h3><ul id="questions"></ul></section><section id="warnings-section" hidden><h3>Warnings</h3><ul id="warnings"></ul></section></div></section>

    <section id="how-it-works" class="grid" style="margin-top: 1rem"><article class="card"><h2>How It Works</h2><div class="flow"><span>Site Data</span><b class="arrow">↓</b><span>Readiness Analysis</span><b class="arrow">↓</b><span>Bitcoin / AI Scores</span><b class="arrow">↓</b><span>Qualification Result</span></div></article><article id="api" class="card"><h2>API</h2><div class="endpoint"><span class="method">GET</span><code>/health</code></div><div class="endpoint"><span class="method">GET</span><code>/.well-known/xagent-verification.json</code></div><div class="endpoint"><span class="method">POST</span><code>/v1/qualify</code></div><div class="endpoint"><span class="method">POST</span><code>/v1/paid/qualify</code></div></article></section>

    <section id="x402" class="card" style="margin-top: 1rem"><h2>x402 Payment Demo</h2><p class="help">This browser demo sends the example payload without payment. It only demonstrates the HTTP 402 boundary and never signs or executes a payment.</p><button id="paid-button" class="secondary" type="button">Test Paid Route</button><p id="paid-status" class="status" role="status" aria-live="polite"></p><div id="payment-result" class="payment-result" hidden><div class="result-top"><h3>Status: <span class="status success">402 Payment Required</span></h3><code id="payment-error"></code></div><div class="grid" style="margin-top: 1rem"><div class="proof"><div><strong>Network:</strong> <span id="payment-network"></span></div><div><strong>Protocol:</strong> <span id="payment-protocol"></span></div><div><strong>Asset:</strong> <span id="payment-asset"></span></div></div><div class="proof"><div><strong>Amount:</strong> <span id="payment-amount"></span></div><div><strong>Seller:</strong> <code id="payment-seller"></code></div><div><strong>Fee payer:</strong> <code id="payment-fee-payer"></code></div></div></div></div></section>

    <section id="proof" class="card" style="margin-top: 1rem"><h2>Successful Hedera Payment Proof</h2><p class="help">Inline view of the existing redacted proof. No keys or signed payloads are shown.</p><div class="grid"><div class="proof"><div><strong>Network:</strong> <code>hedera:testnet</code></div><div><strong>Buyer:</strong> <code>0.0.10488940</code></div><div><strong>Seller:</strong> <code>0.0.10489770</code></div><div><strong>Fee payer:</strong> <code>0.0.7162784</code></div><div><strong>Amount:</strong> <code>100000</code> tinybars / <code>0.001</code> HBAR</div></div><div class="proof"><div><strong>Initial HTTP:</strong> <code>402</code></div><div><strong>Blocky402 verify:</strong> <span class="status success">SUCCESS</span></div><div><strong>Blocky402 settle:</strong> <span class="status success">SUCCESS</span></div><div><strong>Final HTTP:</strong> <code>200</code></div><div><strong>Classification:</strong> <span class="status success">READY</span></div></div></div><p><strong>Transaction ID:</strong> <code>0.0.7162784@1789186391.831327025</code><br><strong>Consensus timestamp:</strong> <code>2026-09-12T04:13:18Z</code></p><p><a class="button secondary" href="#proof">View Successful Payment Proof</a> <a href="https://github.com/CryptoLeaks/powered-site-qualifier/blob/main/evidence/hedera-real/payment-proof-redacted.json">View raw proof on GitHub</a></p></section>

    <p class="note">This is an initial qualification tool and does not replace engineering, utility, legal, or financial due diligence.</p><footer>Live API · HTTPS enabled · Public source code · No tracking</footer>
  </main>
  <script>
    (() => {
      const $ = (id) => document.getElementById(id);
      const value = (id) => $(id).value.trim();
      const nullable = (id) => value(id) || null;
      const numberOrNull = (id) => value(id) === '' ? null : Number(value(id));
      const example = { country_state: 'Oklahoma, USA', intended_use: 'both', available_mw: 20, power_ready_now: true, energization_rfs_date: '2026-10-15', grid_or_gas_to_power: 'grid', power_price_usd_kwh: 0.055, voltage: '138 kV', utility_interconnection_status: 'interconnected', land_size_acres: 120, lease_sale_jv: 'lease', fiber_availability: 'available', water_availability: 'available', gas_availability: null, permitting_status: 'approved', expansion_capacity_mw: 35 };
      function payload() { return { country_state: nullable('country_state'), intended_use: value('intended_use'), available_mw: numberOrNull('available_mw'), power_ready_now: value('power_ready_now') === '' ? null : value('power_ready_now') === 'true', energization_rfs_date: nullable('energization_rfs_date'), voltage: nullable('voltage'), utility_interconnection_status: nullable('utility_interconnection_status'), grid_or_gas_to_power: nullable('grid_or_gas_to_power'), power_price_usd_kwh: numberOrNull('power_price_usd_kwh'), land_size_acres: numberOrNull('land_size_acres'), lease_sale_jv: nullable('lease_sale_jv'), fiber_availability: nullable('fiber_availability'), water_availability: nullable('water_availability'), gas_availability: nullable('gas_availability'), permitting_status: nullable('permitting_status'), expansion_capacity_mw: numberOrNull('expansion_capacity_mw') }; }
      function setField(id, val) { const el = $(id); if (el) el.value = val == null ? '' : val; }
      function loadExample() { setField('country_state', example.country_state); setField('intended_use', example.intended_use); setField('available_mw', example.available_mw); setField('power_ready_now', String(example.power_ready_now)); setField('energization_rfs_date', example.energization_rfs_date); setField('grid_or_gas_to_power', example.grid_or_gas_to_power); setField('power_price_usd_kwh', example.power_price_usd_kwh); setField('voltage', example.voltage); setField('utility_interconnection_status', example.utility_interconnection_status); setField('land_size_acres', example.land_size_acres); setField('lease_sale_jv', example.lease_sale_jv); setField('fiber_availability', example.fiber_availability); setField('water_availability', example.water_availability); setField('gas_availability', ''); setField('permitting_status', example.permitting_status); setField('expansion_capacity_mw', example.expansion_capacity_mw); setField('notes', 'Fictional demo site for judges; no confidential deal data.'); $('form-status').textContent = 'Example site loaded. Ready to analyze.'; $('form-status').className = 'status success'; }
      function list(id, items) { const el = $(id); el.replaceChildren(); (items && items.length ? items : ['None reported']).forEach((item) => { const li = document.createElement('li'); li.textContent = item; el.appendChild(li); }); }
      function renderResult(data) { $('results').hidden = false; $('classification').textContent = data.classification || 'Unknown'; $('result-intended').textContent = 'Intended use: ' + (data.intended_use || 'both'); const bitcoin = data.bitcoin_mining_readiness?.score ?? 0; const ai = data.ai_data_center_readiness?.score ?? 0; $('bitcoin-score').textContent = bitcoin; $('ai-score').textContent = ai; $('bitcoin-bar').style.width = Math.max(0, Math.min(100, bitcoin)) + '%'; $('ai-bar').style.width = Math.max(0, Math.min(100, ai)) + '%'; list('positives', data.key_positives); list('blockers', data.major_blockers); list('missing', data.missing_information); list('questions', data.recommended_next_questions); const warnings = data.warnings || data.warning; $('warnings-section').hidden = !(warnings && warnings.length); if (warnings && warnings.length) list('warnings', Array.isArray(warnings) ? warnings : [warnings]); $('results').scrollIntoView({ behavior: 'smooth', block: 'start' }); }
      function parsePaymentHeader(response) { const encoded = response.headers.get('PAYMENT-REQUIRED'); if (!encoded) return null; try { return JSON.parse(atob(encoded)); } catch (_) { return null; } }
      function formatNetwork(network) { return network === 'hedera:testnet' ? 'Hedera Testnet' : (network || 'Unknown'); }
      function formatAmount(amount) { const tinybars = String(amount || ''); const hbar = Number(tinybars) / 100000000; return tinybars + ' tinybars / ' + (Number.isFinite(hbar) ? hbar.toFixed(3) : 'unknown') + ' HBAR'; }
      function renderPayment(data, response) { const requirement = data.accepts?.[0] || parsePaymentHeader(response)?.accepts?.[0]; if (!requirement) throw new Error('Payment requirement was not returned'); $('payment-network').textContent = formatNetwork(requirement.network); $('payment-protocol').textContent = 'x402 v' + (data.x402Version || '2') + ' ' + (requirement.scheme || 'exact'); $('payment-asset').textContent = (requirement.asset === '0.0.0' ? 'Native HBAR' : 'Asset ' + (requirement.asset || 'unknown')) + ' (' + (requirement.asset || 'unknown') + ')'; $('payment-amount').textContent = formatAmount(requirement.amount); $('payment-seller').textContent = requirement.payTo || 'Unknown'; $('payment-fee-payer').textContent = requirement.extra?.feePayer || 'Not supplied'; $('payment-error').textContent = data.error || 'Payment required'; $('payment-result').hidden = false; }
      async function postJSON(url, body) { const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }); let data = {}; try { data = await response.json(); } catch (_) { data = { error: 'Non-JSON response' }; } return { response, data }; }
      $('example-button').addEventListener('click', loadExample);
      $('qualify-form').addEventListener('submit', async (event) => { event.preventDefault(); const button = $('run-button'); button.disabled = true; $('form-status').textContent = 'Analyzing site...'; $('form-status').className = 'status'; try { const { response, data } = await postJSON('/v1/qualify', payload()); if (!response.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : 'HTTP ' + response.status); renderResult(data); $('form-status').textContent = 'Qualification complete'; $('form-status').className = 'status success'; } catch (error) { $('form-status').textContent = error instanceof TypeError ? 'Unable to reach API' : 'Unable to reach API: ' + error.message; $('form-status').className = 'status error'; } finally { button.disabled = false; } });
      $('paid-button').addEventListener('click', async () => { const button = $('paid-button'); button.disabled = true; $('paid-status').textContent = 'Testing unpaid route...'; $('paid-status').className = 'status'; $('payment-result').hidden = true; try { const { response, data } = await postJSON('/v1/paid/qualify', example); if (response.status !== 402) throw new Error('Expected HTTP 402, received HTTP ' + response.status); renderPayment(data, response); $('paid-status').textContent = 'Unpaid request correctly returned HTTP 402. No payment was executed.'; $('paid-status').className = 'status success'; } catch (error) { $('paid-status').textContent = error instanceof TypeError ? 'Unable to reach API' : error.message; $('paid-status').className = 'status error'; } finally { button.disabled = false; } });
      async function loadHealth() { try { const response = await fetch('/health', { cache: 'no-store' }); if (!response.ok) throw new Error('HTTP ' + response.status); const health = await response.json(); $('api-status').textContent = 'Online'; $('api-status').className = 'status success'; $('health-status').textContent = String(response.status); $('health-status').className = 'status success'; $('https-status').textContent = location.protocol === 'https:' ? 'Active' : 'Not active'; $('https-status').className = 'status ' + (location.protocol === 'https:' ? 'success' : 'error'); if (health.commit) $('api-status').title = 'Reviewed commit: ' + health.commit; } catch (_) { $('api-status').textContent = 'Offline'; $('api-status').className = 'status error'; $('health-status').textContent = 'Unavailable'; $('health-status').className = 'status error'; $('https-status').textContent = location.protocol === 'https:' ? 'Active' : 'Not active'; } }
      loadHealth();
    })();
  </script>
</body>
</html>"""


def _site_dict(request: SiteQualificationRequest) -> dict[str, Any]:
    data = request.model_dump()
    return {
        "power_ready": data["power_ready_now"], "available_mw": data["available_mw"],
        "energization_rfs_date": data["energization_rfs_date"], "utility_status": data["utility_interconnection_status"],
        "grid_or_gas": data["grid_or_gas_to_power"], "power_price": data["power_price_usd_kwh"],
        "land_size": data["land_size_acres"], "lease_sale_jv": data["lease_sale_jv"],
        "fiber": data["fiber_availability"], "water": data["water_availability"],
        "permitting_status": data["permitting_status"], "expansion_capacity": data["expansion_capacity_mw"],
        "intended_use": data["intended_use"],
    }


@app.get("/", response_class=HTMLResponse)
def landing_page() -> HTMLResponse:
    return HTMLResponse(content=LANDING_PAGE)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "commit": COMMIT}


@app.get("/.well-known/xagent-verification.json")
def verification() -> dict[str, Any]:
    return {"schemaVersion": 1, "slug": SLUG, "commit": COMMIT}


@app.post("/v1/qualify")
def qualify_site(request: SiteQualificationRequest) -> dict[str, Any]:
    return qualify(_site_dict(request))


@app.post("/v1/paid/qualify")
def paid_qualify(raw_request: Request, request: SiteQualificationRequest) -> Any:
    """x402-gated version of the qualification capability."""
    required = payment_required_response()
    payment_header = raw_request.headers.get("PAYMENT-SIGNATURE") or raw_request.headers.get("X-PAYMENT")
    if not payment_header:
        return JSONResponse(
            status_code=402,
            content=required,
            headers={
                "PAYMENT-REQUIRED": encode_payment_required(required),
                "Access-Control-Expose-Headers": "PAYMENT-REQUIRED",
            },
        )
    try:
        payment = verify_and_settle(decode_payment_payload(payment_header))
    except (RuntimeError, ValueError) as exc:
        return JSONResponse(status_code=402, content={"error": "Payment not accepted", "reason": str(exc)})
    result = qualify(_site_dict(request))
    result["x402_payment"] = {
        "network": payment.network,
        "payer": payment.payer,
        "transaction": payment.transaction,
    }
    return JSONResponse(
        status_code=200,
        content=result,
        headers={"PAYMENT-RESPONSE": encode_payment_required(result["x402_payment"])},
    )
