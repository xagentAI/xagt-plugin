let G = () => document.getElementById('gate').value.replace(/\/$/, '');
let C = () => document.getElementById('crm').value.replace(/\/$/, '');
let SID = null, CURSOR = null, PAGE = 0, MODE = 'normal', RES = 'invoice', TOTAL = 0, CLAIM_N = 100;
async function jget(u) { const r = await fetch(u); if (!r.ok) throw new Error(r.status); return r.json(); }
async function jpost(u, b) { const r = await fetch(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(b) }); if (!r.ok) throw new Error(await r.text()); return r.json(); }
async function startDemo(mode) {
  MODE = mode; RES = 'invoice'; PAGE = 0; CURSOR = null; TOTAL = 0; CLAIM_N = 100;
  const s = await jpost(G() + '/v1/sessions', { resource_type: 'invoice', source: 'demo-crm', scope: { status: 'unpaid' } });
  SID = s.session_id;
  document.getElementById('sid').textContent = SID;
  document.getElementById('sess').style.display = 'block';
  document.getElementById('claimText').value = mode === 'timeout_page_3' ? 'There are no overdue invoices.' : 'There are exactly 100 unpaid invoices.';
  await fetchNext();
}
async function startMinDemo() {
  MODE = 'normal'; RES = 'product'; PAGE = 0; CURSOR = null; TOTAL = 0;
  const s = await jpost(G() + '/v1/sessions', { resource_type: 'product', source: 'demo-crm', scope: {} });
  SID = s.session_id;
  document.getElementById('sid').textContent = SID;
  document.getElementById('sess').style.display = 'block';
  document.getElementById('claimText').value = 'prod_001 is the cheapest product.';
  await fetchNext();
}
async function fetchNext() {
  const ep = RES === 'invoice' ? '/invoices?mode=' + MODE : '/products';
  const url = C() + ep + (ep.includes('?') ? '&' : '?') + (CURSOR ? 'cursor=' + CURSOR : '');
  PAGE++;
  try {
    const d = await jget(url);
    TOTAL += d.records.length;
    const items = RES === 'product' ? d.records.map(r => ({ id: r.id, price: r.price })) : [];
    const o = await jpost(G() + '/v1/sessions/' + SID + '/observe',
      { page_number: PAGE, cursor_in: CURSOR, cursor_out: d.cursor_out, has_more: d.has_more, records_seen: d.records.length, items, scope: RES === 'invoice' ? { status: 'unpaid' } : {}, snapshot_id: d.snapshot_id, authoritative_total: d.authoritative_total });
    CURSOR = d.cursor_out;
    update(o.pages_seen, TOTAL, d.has_more, d.snapshot_id);
  } catch (e) {
    await jpost(G() + '/v1/sessions/' + SID + '/failure', { page_number: PAGE, kind: 'timeout', message: String(e).slice(0, 200) });
    const s = await jget(G() + '/v1/sessions/' + SID);
    update(s.observation_count, TOTAL, true, '—');
    document.getElementById('cursor').textContent = 'page ' + PAGE + ' failed (recorded)';
  }
}
function update(pages, recs, more, snap) {
  document.getElementById('pages').textContent = pages + (more ? ' / ?' : ' / ' + pages);
  document.getElementById('recs').textContent = recs;
  document.getElementById('snap').textContent = snap || '—';
  const pct = more ? Math.min(90, Math.round(recs / 3.47)) : 100;
  document.getElementById('cov').textContent = pct + '%';
  document.getElementById('bar').style.width = pct + '%';
  document.getElementById('cursor').textContent = more ? ('continuation: ' + CURSOR) : 'exhausted';
  jget(G() + '/v1/sessions/' + SID).then(s => document.getElementById('fails').textContent = s.failure_count);
}
async function verifyClaim() {
  const text = document.getElementById('claimText').value;
  const parsed = await jpost(G() + '/v1/claims/parse', { text });
  let claim = parsed;
  if (parsed.type === 'EXACT_COUNT' && RES === 'invoice') claim = { type: 'EXACT_COUNT', value: TOTAL };
  if (parsed.type === 'MIN' || /cheapest/.test(text)) {
    const obs = await jget(G() + '/v1/sessions/' + SID + '/observations');
    const items = obs.observations.flatMap(o => o.items || []);
    const cheapest = items.length ? items.reduce((a, b) => a.price <= b.price ? a : b) : { id: 'prod_001' };
    claim = { type: 'MIN', field: 'price', candidate_id: cheapest.id };
  }
  const v = await jpost(G() + '/v1/sessions/' + SID + '/verify', { claim });
  const el = document.getElementById('verdict');
  el.textContent = v.verdict; el.className = 'verdict ' + v.verdict;
  document.getElementById('reasons').innerHTML = (v.blocking_reasons || []).map(b => `<span class="pill">${b.code}</span> ${b.message} → <b>${b.recommended_next_action}</b>`).join('<br/>') || '<span class="mut">no blocking reasons</span>';
  document.getElementById('cert').textContent = JSON.stringify(v.certificate || v.evidence_summary, null, 2);
  const sum = v.evidence_summary || {};
  document.getElementById('checks').innerHTML = ['RESULT_SET_COMPLETE', 'NO_UNRESOLVED_FAILURES', 'SCOPE_STABLE', 'SNAPSHOT_ACCEPTABLE'].map(k =>
    `<span class="pill">${k}: ${(v.obligation_status || {})[k] || '?'}</span>`).join(' ');
}
