const state = {
  config: { mode: 'demo', liveReady: false },
  links: [],
  current: null,
  toastTimer: null
};

const $ = (selector) => document.querySelector(selector);
const dashboard = $('#dashboard-view');
const payerView = $('#payer-view');

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  }[char]));
}

function formatAmount(value) {
  const number = Number.parseFloat(value);
  if (!Number.isFinite(number)) return '--';
  return number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatDate(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return date.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function statusClass(status) {
  return `status-${String(status || 'idle').toLowerCase()}`;
}

function statusLabel(status) {
  return String(status || 'waiting').toUpperCase();
}

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { toast.hidden = true; }, 2800);
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, { headers: { accept: 'application/json', ...(options.headers || {}) }, ...options });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.error || `Request failed (${response.status})`);
  return body;
}

function setMode(config) {
  state.config = config;
  const pill = $('#mode-pill');
  const label = $('#mode-label');
  pill.classList.toggle('mode-live', config.mode === 'live');
  pill.classList.toggle('mode-demo', config.mode !== 'live');
  label.textContent = config.mode === 'live' ? 'LIVE MODE' : (config.mode === 'misconfigured' ? 'SETUP NEEDED' : 'DEMO MODE');
  if (config.configurationIssue) showToast(config.configurationIssue);
}

function renderPreview(link) {
  state.current = link;
  const status = $('#preview-status');
  status.className = `status-badge ${statusClass(link?.status || 'idle')}`;
  status.textContent = statusLabel(link?.status || 'waiting');
  const content = $('#preview-content');
  if (!link) {
    content.className = 'preview-content empty-preview';
    content.innerHTML = '<div class="empty-icon">+</div><h3>Your link will appear here</h3><p>Create a request to get a hosted checkout URL.</p>';
    return;
  }

  const canSimulate = state.config.mode === 'demo' && link.status === 'active';
  content.className = 'preview-content link-output';
  content.innerHTML = `
    <div>
      <div class="amount-block"><span class="amount-value">$${escapeHtml(formatAmount(link.toAmount))}</span><span class="amount-currency">USD</span></div>
      <p class="output-description">${escapeHtml(link.description || 'Payment request')}</p>
    </div>
    <div class="url-box"><span class="url-text">${escapeHtml(link.url || '')}</span><button class="copy-button" type="button" data-action="copy">Copy</button></div>
    <div class="output-actions">
      <a class="outline-button accent" href="${escapeHtml(link.url || '#')}" target="_blank" rel="noreferrer">Open checkout -&gt;</a>
      ${canSimulate ? '<button class="outline-button" type="button" data-action="simulate">Simulate payment</button>' : ''}
    </div>
    <div class="output-meta"><span>Created ${escapeHtml(formatDate(link.createdAt))}</span><span>${link.demo ? 'Local demo record' : 'Moove API record'}</span></div>
  `;
  content.querySelector('[data-action="copy"]')?.addEventListener('click', () => copyLink(link.url));
  content.querySelector('[data-action="simulate"]')?.addEventListener('click', () => simulateLink(link.id));
}

async function copyLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    showToast('Checkout URL copied.');
  } catch {
    showToast('Copy failed. Select the URL manually.');
  }
}

function renderRecent() {
  const list = $('#recent-list');
  if (!state.links.length) {
    list.innerHTML = '<div class="list-empty">No requests in this session.</div>';
    return;
  }
  list.innerHTML = state.links.slice(0, 8).map((link) => `
    <button class="recent-row" type="button" data-id="${escapeHtml(link.id)}">
      <span class="recent-main"><span class="recent-title">${escapeHtml(link.description || 'Payment request')}</span><span class="recent-meta">${escapeHtml(formatDate(link.createdAt))}</span></span>
      <span class="recent-amount">$${escapeHtml(formatAmount(link.toAmount))}</span>
      <span class="recent-status status-badge ${statusClass(link.status)}">${escapeHtml(statusLabel(link.status))}</span>
    </button>
  `).join('');
  list.querySelectorAll('[data-id]').forEach((button) => {
    button.addEventListener('click', () => loadLink(button.dataset.id, true));
  });
}

async function loadLinks() {
  try {
    const body = await requestJson('/api/payment-links');
    state.links = Array.isArray(body.links) ? body.links : [];
    renderRecent();
  } catch (error) {
    showToast(error.message);
  }
}

async function loadLink(id, select = false) {
  try {
    const link = await requestJson(`/api/payment-links/${encodeURIComponent(id)}`);
    const index = state.links.findIndex((item) => item.id === link.id);
    if (index >= 0) state.links[index] = { ...state.links[index], ...link };
    else state.links.unshift(link);
    renderRecent();
    if (select) renderPreview(link);
    return link;
  } catch (error) {
    showToast(error.message);
    return null;
  }
}

async function simulateLink(id) {
  try {
    const link = await requestJson(`/api/payment-links/${encodeURIComponent(id)}/simulate`, { method: 'POST' });
    state.links = state.links.map((item) => item.id === link.id ? link : item);
    renderRecent();
    renderPreview(link);
    showToast('Demo settlement recorded.');
  } catch (error) {
    showToast(error.message);
  }
}

async function createLink(event) {
  event.preventDefault();
  const button = $('#create-button');
  const errorBox = $('#form-error');
  errorBox.hidden = true;
  button.disabled = true;
  button.querySelector('span').textContent = 'Creating...';
  const expirationValue = $('#expiration').value;
  try {
    const link = await requestJson('/api/payment-links', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        amount: $('#amount').value,
        item: $('#item').value,
        reference: $('#reference').value,
        expirationDate: expirationValue ? new Date(expirationValue).toISOString() : null
      })
    });
    state.links = [link, ...state.links.filter((item) => item.id !== link.id)];
    renderRecent();
    renderPreview(link);
    showToast(state.config.mode === 'live' ? 'Live Moove link created.' : 'Demo link created.');
  } catch (error) {
    errorBox.textContent = error.message;
    errorBox.hidden = false;
  } finally {
    button.disabled = false;
    button.querySelector('span').textContent = 'Create link';
  }
}

async function initDashboard() {
  try { setMode(await requestJson('/api/config')); } catch (error) { showToast(error.message); }
  $('#link-form').addEventListener('submit', createLink);
  $('#refresh-button').addEventListener('click', async () => {
    await loadLinks();
    if (state.current?.id) await loadLink(state.current.id, true);
    showToast('Ledger refreshed.');
  });
  await loadLinks();
}

async function initPayer() {
  dashboard.hidden = true;
  dashboard.setAttribute('aria-hidden', 'true');
  payerView.hidden = false;
  payerView.setAttribute('aria-hidden', 'false');
  const id = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');
  const content = $('#payer-content');
  try {
    const link = await requestJson(`/api/payment-links/${encodeURIComponent(id)}`);
    const isActive = link.status === 'active';
    const payerAction = link.demo ? 'Simulate payment' : 'Continue to payment';
    content.innerHTML = `
      <div class="amount-block"><span class="amount-value">$${escapeHtml(formatAmount(link.toAmount))}</span><span class="amount-currency">USD</span></div>
      <h2>${escapeHtml(link.description || 'Payment request')}</h2>
      <p class="payer-description">Pay this request through the hosted Moove checkout. The recipient receives the settlement in their configured wallet.</p>
      <div class="payer-reference">Reference: ${escapeHtml(link.description || link.id)}</div>
      ${isActive ? `<button id="payer-action" class="primary-button" type="button"><span>${payerAction}</span><span class="button-arrow">-&gt;</span></button>` : `<div class="status-badge ${statusClass(link.status)}">${escapeHtml(statusLabel(link.status))}</div>`}
    `;
    $('#payer-action')?.addEventListener('click', async () => {
      if (link.demo) {
        const updated = await requestJson(`/api/payment-links/${encodeURIComponent(link.id)}/simulate`, { method: 'POST' });
        content.querySelector('#payer-action').outerHTML = `<div class="status-badge status-completed">SETTLED IN DEMO</div>`;
        showToast(`Received $${formatAmount(updated.receivedAmount || updated.toAmount)}.`);
      } else {
        showToast('Open the hosted Moove checkout to complete payment.');
        window.open(link.url, '_blank', 'noopener,noreferrer');
      }
    });
  } catch (error) {
    content.innerHTML = `<p class="form-error">${escapeHtml(error.message)}</p>`;
  }
}

if (location.pathname.startsWith('/pay/')) initPayer();
else initDashboard();
