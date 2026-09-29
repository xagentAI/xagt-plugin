import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { randomUUID } from 'node:crypto';

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC_DIR = path.join(ROOT, 'public');
const DEFAULT_PORT = 8787;
const BODY_LIMIT = 32 * 1024;
const DEFAULT_SLUG = 'checkout-pilot';

const MIME_TYPES = {
  '.css': 'text/css; charset=utf-8',
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.ico': 'image/x-icon'
};

function json(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    'content-type': 'application/json; charset=utf-8',
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(body)
  });
  res.end(body);
}

function text(res, status, body, contentType = 'text/plain; charset=utf-8') {
  res.writeHead(status, {
    'content-type': contentType,
    'cache-control': 'no-store',
    'content-length': Buffer.byteLength(body)
  });
  res.end(body);
}

function getBaseUrl(env) {
  const value = String(env.MOOVE_API_BASE_URL || '').trim();
  if (!value) return null;
  try {
    const url = new URL(value);
    const localHost = ['localhost', '127.0.0.1', '::1'].includes(url.hostname);
    if (url.protocol !== 'https:' && !(url.protocol === 'http:' && localHost)) return null;
    return url.toString().replace(/\/$/, '');
  } catch {
    return null;
  }
}

function getMode(env) {
  const hasKey = Boolean(String(env.MOOVE_API_KEY || '').trim());
  const baseUrl = getBaseUrl(env);
  const misconfigured = hasKey !== Boolean(baseUrl);
  return {
    mode: misconfigured ? 'misconfigured' : (hasKey ? 'live' : 'demo'),
    liveReady: hasKey && Boolean(baseUrl),
    baseUrl: baseUrl || null,
    configurationIssue: misconfigured
      ? 'Set both MOOVE_API_KEY and MOOVE_API_BASE_URL together to enable live mode.'
      : null
  };
}

function getSourceIdentity(env) {
  const commit = String(env.SOURCE_COMMIT || '').trim().toLowerCase();
  const slug = String(env.XAGENT_SUBMISSION_SLUG || DEFAULT_SLUG).trim().toLowerCase();
  return {
    commit: /^[0-9a-f]{40}$/.test(commit) ? commit : null,
    slug: /^[a-z0-9]+(?:-[a-z0-9]+)+$/.test(slug) ? slug : DEFAULT_SLUG
  };
}

function isPositiveDecimalString(value) {
  if (typeof value !== 'string' || !/^\d+(?:\.\d{1,2})?$/.test(value.trim())) return false;
  const normalized = value.trim();
  return !/^0+(?:\.0{1,2})?$/.test(normalized);
}

function canonicalAmount(value) {
  const normalized = String(value).trim();
  const [whole, fraction = ''] = normalized.split('.');
  const cleanWhole = whole.replace(/^0+(?=\d)/, '') || '0';
  return fraction ? `${cleanWhole}.${fraction.padEnd(2, '0')}` : `${cleanWhole}.00`;
}

export function validatePaymentInput(payload) {
  if (!payload || typeof payload !== 'object') {
    return { ok: false, error: 'Send a JSON object.' };
  }

  const rawAmount = payload.amount ?? payload.toAmount ?? '';
  if (typeof rawAmount !== 'string') {
    return { ok: false, error: 'Amount must be a decimal string, not a number.' };
  }
  const amount = rawAmount.trim();
  if (!isPositiveDecimalString(amount)) {
    return { ok: false, error: 'Amount must be a positive decimal with up to two decimals.' };
  }

  const item = String(payload.item ?? '').trim();
  const reference = String(payload.reference ?? '').trim();
  if (item.length > 80) return { ok: false, error: 'Item name is limited to 80 characters.' };
  if (reference.length > 48) return { ok: false, error: 'Reference is limited to 48 characters.' };

  const safeReference = reference || `CP-${new Date().toISOString().slice(0, 10).replaceAll('-', '')}`;
  const description = item ? `${safeReference} | ${item}` : safeReference;
  if (description.length > 120) return { ok: false, error: 'Item and reference create a description over 120 characters.' };

  let expirationDate = null;
  if (payload.expirationDate) {
    const parsed = new Date(String(payload.expirationDate));
    if (Number.isNaN(parsed.getTime())) return { ok: false, error: 'Expiration must be a valid date.' };
    if (parsed.getTime() <= Date.now()) return { ok: false, error: 'Expiration must be in the future.' };
    expirationDate = parsed.toISOString();
  }

  return {
    ok: true,
    value: {
      toAmount: canonicalAmount(amount),
      description,
      maxUsage: 1,
      expirationDate,
      item,
      reference: safeReference
    }
  };
}

function originFor(req) {
  const forwarded = String(req.headers['x-forwarded-proto'] || '').split(',')[0].trim();
  const protocol = forwarded || 'http';
  const host = req.headers.host || `127.0.0.1:${DEFAULT_PORT}`;
  return `${protocol}://${host}`;
}

function demoLink(input, origin) {
  const id = `demo-${randomUUID()}`;
  return {
    id,
    url: `${origin}/pay/${id}`,
    status: 'active',
    toAmount: input.toAmount,
    description: input.description,
    maxUsage: input.maxUsage,
    expirationDate: input.expirationDate,
    createdAt: new Date().toISOString(),
    demo: true
  };
}

function unwrap(value) {
  if (value && typeof value === 'object' && value.data && typeof value.data === 'object' && !Array.isArray(value.data)) {
    return value.data;
  }
  return value;
}

function normalizeLink(value, fallback = {}) {
  const item = unwrap(value) || {};
  return {
    ...fallback,
    ...item,
    id: item.id || fallback.id || null,
    url: item.url || fallback.url || null,
    status: item.status || fallback.status || 'active',
    toAmount: item.toAmount || item.amount || fallback.toAmount || null,
    description: item.description || fallback.description || null
  };
}

function publicApiError(status, code) {
  if (status === 401) return { status: 502, error: 'Moove rejected the API key. Check it in the dashboard.' };
  if (status === 403) return { status: 502, error: 'The API key does not have the required payment-link scope.' };
  if (status === 404) return { status: 404, error: 'Payment link was not found for this API key.' };
  if (status === 409) return { status: 409, error: 'The Moove account needs a claimed Handle and default settlement wallet.' };
  return { status: 502, error: `Moove API request failed${code ? ` (${code})` : ''}.` };
}

async function mooveRequest(env, route, options = {}) {
  const baseUrl = getBaseUrl(env);
  const apiKey = String(env.MOOVE_API_KEY || '').trim();
  if (!baseUrl || !apiKey) {
    const error = new Error('Live mode is not configured.');
    error.publicStatus = 503;
    throw error;
  }

  const response = await fetch(`${baseUrl}${route}`, {
    ...options,
    headers: {
      ...(options.body ? { 'content-type': 'application/json' } : {}),
      'X-API-Key': apiKey,
      ...(options.headers || {})
    },
    signal: AbortSignal.timeout(15_000)
  });
  const raw = await response.text();
  let body = null;
  try { body = raw ? JSON.parse(raw) : null; } catch { body = null; }
  if (!response.ok) {
    const code = body?.code || body?.error?.code;
    const mapped = publicApiError(response.status, code);
    const error = new Error(mapped.error);
    error.publicStatus = mapped.status;
    throw error;
  }
  return body;
}

async function readBody(req) {
  const chunks = [];
  let size = 0;
  for await (const chunk of req) {
    size += chunk.length;
    if (size > BODY_LIMIT) {
      const error = new Error('Request body is too large.');
      error.publicStatus = 413;
      throw error;
    }
    chunks.push(chunk);
  }
  const raw = Buffer.concat(chunks).toString('utf8');
  if (!raw) return {};
  try { return JSON.parse(raw); } catch {
    const error = new Error('Request body must be valid JSON.');
    error.publicStatus = 400;
    throw error;
  }
}

async function serveStatic(req, res, pathname) {
  let requested = pathname === '/' ? '/index.html' : pathname;
  try { requested = decodeURIComponent(requested); } catch { return text(res, 400, 'Bad path'); }
  const candidate = path.resolve(PUBLIC_DIR, `.${requested}`);
  if (!candidate.startsWith(`${PUBLIC_DIR}${path.sep}`)) return text(res, 403, 'Forbidden');
  try {
    const info = await fs.stat(candidate);
    if (!info.isFile()) return text(res, 404, 'Not found');
    const body = await fs.readFile(candidate);
    const type = MIME_TYPES[path.extname(candidate).toLowerCase()] || 'application/octet-stream';
    res.writeHead(200, { 'content-type': type, 'cache-control': 'no-store', 'content-length': body.length });
    res.end(body);
  } catch {
    if (pathname.startsWith('/pay/')) {
      const body = await fs.readFile(path.join(PUBLIC_DIR, 'index.html'));
      res.writeHead(200, { 'content-type': MIME_TYPES['.html'], 'cache-control': 'no-store', 'content-length': body.length });
      res.end(body);
      return;
    }
    text(res, 404, 'Not found');
  }
}

export function createAppServer({ env = process.env, store = new Map(), now = () => Date.now() } = {}) {
  const server = http.createServer(async (req, res) => {
    const requestUrl = new URL(req.url || '/', originFor(req));
    const pathname = requestUrl.pathname;
    const method = req.method || 'GET';
    const config = getMode(env);
    const source = getSourceIdentity(env);

    try {
      if (pathname === '/health' && method === 'GET') {
        return json(res, 200, {
          status: 'ok',
          service: 'checkout-pilot',
          mode: config.mode,
          commit: source.commit || 'development'
        });
      }
      if (pathname === '/.well-known/xagent-verification.json' && method === 'GET') {
        if (!source.commit) {
          return json(res, 503, {
            error: 'SOURCE_COMMIT must be a 40-character Git commit in a public deployment.'
          });
        }
        return json(res, 200, {
          schemaVersion: 1,
          slug: source.slug,
          commit: source.commit
        });
      }
      if (pathname === '/api/capabilities' && method === 'GET') {
        return json(res, 200, {
          name: 'Checkout Pilot',
          description: 'Create one-off, referenceable payment requests and read settlement status.',
          sideEffects: {
            createPaymentRequest: 'Creates a payment request but never sends, swaps, or withdraws funds.',
            readPaymentStatus: 'Read-only.'
          },
          operations: [
            {
              id: 'create_payment_request',
              method: 'POST',
              path: '/api/payment-links',
              required: ['amount'],
              optional: ['item', 'reference', 'expirationDate']
            },
            {
              id: 'get_payment_request',
              method: 'GET',
              path: '/api/payment-links/{id}'
            }
          ],
          constraints: [
            'Amounts are positive decimal strings with at most two fractional digits.',
            'Live creation requires a server-side Moove Receive API key.',
            'The service never accepts private keys or destination wallet parameters.'
          ]
        });
      }
      if (pathname === '/api/config' && method === 'GET') {
        return json(res, 200, {
          mode: config.mode,
          liveReady: config.liveReady,
          configurationIssue: config.configurationIssue
        });
      }

      if (pathname === '/api/payment-links' && method === 'POST') {
        if (config.mode === 'misconfigured') return json(res, 503, { error: config.configurationIssue });
        const payload = await readBody(req);
        const validation = validatePaymentInput(payload);
        if (!validation.ok) return json(res, 400, { error: validation.error });

        if (config.mode === 'demo') {
          const link = demoLink(validation.value, originFor(req));
          store.set(link.id, link);
          return json(res, 201, link);
        }

        const remote = await mooveRequest(env, '/v1/payment-link', {
          method: 'POST',
          body: JSON.stringify({
            toAmount: validation.value.toAmount,
            description: validation.value.description,
            maxUsage: validation.value.maxUsage,
            expirationDate: validation.value.expirationDate
          })
        });
        const link = normalizeLink(remote, { demo: false, createdAt: new Date(now()).toISOString() });
        if (link.id) store.set(link.id, link);
        return json(res, 201, link);
      }

      if (pathname === '/api/payment-links' && method === 'GET') {
        if (config.mode === 'misconfigured') return json(res, 503, { error: config.configurationIssue });
        if (config.mode === 'demo') {
          const links = [...store.values()].sort((a, b) => String(b.createdAt).localeCompare(String(a.createdAt)));
          return json(res, 200, { links });
        }
        const remote = await mooveRequest(env, '/v1/payment-link?offset=0', { method: 'GET' });
        const list = Array.isArray(remote) ? remote : (Array.isArray(remote?.data) ? remote.data : (Array.isArray(remote?.items) ? remote.items : []));
        return json(res, 200, { links: list.map((item) => normalizeLink(item, { demo: false })) });
      }

      const match = pathname.match(/^\/api\/payment-links\/([^/]+)(\/simulate)?$/);
      if (match && method === 'POST' && match[2] === '/simulate') {
        if (config.mode !== 'demo') return json(res, 409, { error: 'Simulation is available only in demo mode.' });
        const link = store.get(decodeURIComponent(match[1]));
        if (!link) return json(res, 404, { error: 'Demo payment link not found.' });
        link.status = 'completed';
        link.receivedAmount = link.toAmount;
        link.completedAt = new Date(now()).toISOString();
        return json(res, 200, link);
      }

      if (match && method === 'GET') {
        if (config.mode === 'misconfigured') return json(res, 503, { error: config.configurationIssue });
        const id = decodeURIComponent(match[1]);
        if (config.mode === 'demo') {
          const link = store.get(id);
          if (!link) return json(res, 404, { error: 'Demo payment link not found.' });
          return json(res, 200, link);
        }
        const remote = await mooveRequest(env, `/v1/payment-link/${encodeURIComponent(id)}`, { method: 'GET' });
        return json(res, 200, normalizeLink(remote, { id, demo: false }));
      }

      return serveStatic(req, res, pathname);
    } catch (error) {
      const status = Number(error.publicStatus) || 500;
      if (status >= 500) console.error(`[checkout-pilot] ${error.message}`);
      return json(res, status, { error: error.message || 'Unexpected server error.' });
    }
  });
  return server;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || DEFAULT_PORT);
  const server = createAppServer();
  server.listen(port, '0.0.0.0', () => {
    console.log(`Checkout Pilot running on port ${port}`);
    console.log(`Mode: ${getMode(process.env).mode}`);
  });
}
