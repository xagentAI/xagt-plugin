// OKX x402 paywall for the acceptance-gate worker (plain module worker, no hono).
//
// Protocol/source-of-truth notes (verified against @okxweb3/x402-core@0.1.0 and
// @okxweb3/x402-evm@0.2.1 dist sources plus OKX seller-SDK docs):
//   - x402 v2 challenge: HTTP 402 + `PAYMENT-REQUIRED` header = base64(JSON of
//     { x402Version: 2, error, resource, accepts: [paymentRequirements] }).
//     We additionally mirror the same JSON into the response body for humans.
//   - Buyer payment arrives base64-encoded in `PAYMENT` (official buyer SDK),
//     `PAYMENT-SIGNATURE` (x402-core server default) or `X-PAYMENT` — checked
//     in that order.
//   - Facilitator = OKX hosted, HMAC-SHA256 signed (OKXFacilitatorClient):
//       POST https://web3.okx.com/api/v6/pay/x402/verify
//       POST https://web3.okx.com/api/v6/pay/x402/settle   (body carries syncSettle)
//       GET  https://web3.okx.com/api/v6/pay/x402/supported
//       GET  https://web3.okx.com/api/v6/pay/x402/settle/status?txHash=...
//     prehash = timestamp + METHOD + path(+query) + body, timestamp = ISO-8601,
//     headers OK-ACCESS-KEY / OK-ACCESS-SIGN / OK-ACCESS-TIMESTAMP / OK-ACCESS-PASSPHRASE.
//     Responses use the OKX { code, msg, data } envelope; code !== "0" is a
//     business error even on HTTP 200.
//   - Settlement semantics (syncSettle=true): only `status: "success"` means
//     funds confirmed on-chain. `pending` = broadcast but NOT confirmed and
//     `timeout` = confirmation timed out — in both cases we keep polling
//     GET settle/status and never deliver data until it reports success.
//   - Settlement result is surfaced to the buyer via `PAYMENT-RESPONSE` header
//     = base64(JSON settle response).
//
// Uses WebCrypto (crypto.subtle) for HMAC so no nodejs_compat flag is required.

const FACILITATOR_BASE_URL = 'https://web3.okx.com';
const X402_VERSION = 2;

// X Layer mainnet + OKX default stablecoin USDT0 (EIP-3009, 6 decimals).
// Address/name/version copied from @okxweb3/x402-evm DEFAULT_STABLECOINS['eip155:196'].
export const X402_NETWORK = 'eip155:196';
export const X402_SCHEME = 'exact';
export const X402_PAY_TO = '0x1e1a2f7ac1bc6df29a1878c3f26b17dccdc16e15';
export const X402_ASSET = {
  address: '0x779ded0c9e1022225f8e0630b35a9b54be713736',
  name: 'USD₮0',
  version: '1',
  decimals: 6
};
// Default price when no per-route override (legacy 1 USDT).
export const X402_PRICE_ATOMIC = '1000000';
const MAX_TIMEOUT_SECONDS = 300;

// Extra CORS surface needed only when the paywall is active. Kept out of the
// worker's base headers so X402_ENABLED=false responses stay byte-identical
// with the pre-paywall deployment.
export const X402_CORS_HEADERS = {
  'access-control-allow-headers': 'content-type, payment, payment-signature, x-payment',
  'access-control-expose-headers': 'payment-required, payment-response'
};

// Settlement polling budget. syncSettle usually confirms in-band; when it
// returns pending/timeout we keep polling settle/status for up to ~20s more
// (well inside Workers request limits). Tunable via env for tests.
const DEFAULT_SETTLE_POLL_BUDGET_MS = 20_000;
const DEFAULT_SETTLE_POLL_INTERVAL_MS = 1_000;

// Best-effort receipt store so a buyer whose settlement came back
// pending/timeout can replay the SAME payment header and collect the data once
// the tx confirms, without being charged twice (the EIP-3009 nonce is burned,
// so a second settle would fail anyway).
// LIMITATION: this Map is per-isolate. Cloudflare may route the retry to a
// different isolate or recycle this one, in which case we fall back to the
// normal verify path (which will reject the burned nonce). Durable receipts
// would need KV/DO — out of scope for this stage.
const RECEIPT_TTL_MS = 10 * 60 * 1000;
const receiptCache = new Map(); // paymentHash -> { status, txHash, settleResponse, storedAt }

/** Whether the paywall is switched on. Anything except the string "true" keeps
 * the worker in its historical free mode (safe during marketplace review). */
export function isX402Enabled(env) {
  return env?.X402_ENABLED === 'true';
}

/** Payment requirements advertised for a paid endpoint. */
export function buildPaymentRequirements({ amountAtomic = X402_PRICE_ATOMIC } = {}) {
  return {
    scheme: X402_SCHEME,
    network: X402_NETWORK,
    amount: amountAtomic,
    asset: X402_ASSET.address,
    payTo: X402_PAY_TO,
    maxTimeoutSeconds: MAX_TIMEOUT_SECONDS,
    // EIP-712 domain for the EIP-3009 transferWithAuthorization signature.
    extra: { name: X402_ASSET.name, version: X402_ASSET.version }
  };
}

function buildPaymentRequired({ resourceUrl, description, error, amountAtomic }) {
  const paymentRequired = {
    x402Version: X402_VERSION,
    resource: {
      url: resourceUrl,
      description: description || '',
      mimeType: 'application/json'
    },
    accepts: [buildPaymentRequirements({ amountAtomic })]
  };
  if (error) paymentRequired.error = error;
  return paymentRequired;
}

/**
 * Gate a paid endpoint behind the OKX x402 flow.
 *
 * @param request  incoming Request (body untouched unless payment verifies)
 * @param env      worker env (OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE)
 * @param options  { resourceUrl, description, deliver, respond }
 *   deliver: async () => payload object (only invoked after verify passes;
 *            responsible for parsing the request body itself)
 *   respond: (payload, status, extraHeaders) => Response
 * @returns Response
 */
export async function handlePaidRequest(request, env, { resourceUrl, description, deliver, respond, priceAtomic = X402_PRICE_ATOMIC }) {
  const challenge = (error) => {
    const paymentRequired = buildPaymentRequired({ resourceUrl, description, error, amountAtomic: priceAtomic });
    return respond(paymentRequired, 402, {
      'PAYMENT-REQUIRED': base64EncodeUtf8(JSON.stringify(paymentRequired))
    });
  };

  // Challenge is issued before any body parsing: unpaid probes cost nothing.
  const rawHeader = request.headers.get('payment')
    || request.headers.get('payment-signature')
    || request.headers.get('x-payment');
  if (!rawHeader) {
    return challenge('Payment required');
  }

  let paymentPayload;
  try {
    paymentPayload = JSON.parse(base64DecodeUtf8(rawHeader));
  } catch {
    return challenge('Invalid payment header: expected base64-encoded JSON payment payload');
  }
  if (!paymentPayload || paymentPayload.x402Version !== X402_VERSION || !paymentPayload.accepted) {
    return challenge('Invalid payment payload: x402Version must be 2 with an accepted requirements object');
  }

  // Reject payments signed for a different resource (cross-endpoint reuse).
  if (paymentPayload.resource?.url && paymentPayload.resource.url !== resourceUrl) {
    return challenge('Payment resource mismatch: payment was created for a different resource URL');
  }

  const requirements = buildPaymentRequirements({ amountAtomic: priceAtomic });
  if (!requirementsMatch(requirements, paymentPayload.accepted)) {
    return challenge('No matching payment requirements found');
  }

  // Replay path: same payment header seen before in this isolate.
  const receiptKey = await sha256Hex(canonicalJson(paymentPayload));
  pruneReceipts();
  const receipt = receiptCache.get(receiptKey);
  if (receipt?.status === 'success') {
    // Already settled — deliver without contacting the facilitator again.
    return deliverPayload(deliver, respond, receipt.settleResponse);
  }
  if (receipt?.status === 'pending' && receipt.txHash) {
    return resolvePendingReceipt(env, receiptKey, receipt, { deliver, respond, requirements });
  }

  // 1) verify with the OKX hosted facilitator
  let verifyResult;
  try {
    verifyResult = await facilitatorRequest(env, 'POST', '/api/v6/pay/x402/verify', {
      x402Version: X402_VERSION,
      paymentPayload,
      paymentRequirements: requirements
    });
  } catch (error) {
    return facilitatorErrorResponse(respond, 'verify', error);
  }
  if (!verifyResult || verifyResult.isValid !== true) {
    return challenge(verifyResult?.invalidReason || 'Payment verification failed');
  }

  // 2) produce the deliverable before settling so a data failure never burns a payment
  let payload;
  try {
    payload = await deliver();
  } catch (error) {
    return respond({
      error: 'internal_error',
      message: error instanceof Error ? error.message : String(error)
    }, 500);
  }

  // 3) settle synchronously (syncSettle) — only hand over data once funds confirmed
  let settleResult;
  try {
    settleResult = await facilitatorRequest(env, 'POST', '/api/v6/pay/x402/settle', {
      x402Version: X402_VERSION,
      paymentPayload,
      paymentRequirements: requirements,
      syncSettle: true
    });
  } catch (error) {
    return facilitatorErrorResponse(respond, 'settle', error);
  }

  const outcome = await resolveSettlement(env, settleResult);

  if (outcome.state === 'settled') {
    receiptCache.set(receiptKey, {
      status: 'success',
      txHash: outcome.settleResponse.transaction,
      settleResponse: outcome.settleResponse,
      storedAt: Date.now()
    });
    return respond(payload, 200, paymentResponseHeader(outcome.settleResponse));
  }

  if (outcome.state === 'pending') {
    receiptCache.set(receiptKey, {
      status: 'pending',
      txHash: outcome.settleResponse.transaction,
      settleResponse: outcome.settleResponse,
      storedAt: Date.now()
    });
    return pendingTxResponse(respond, outcome.settleResponse);
  }

  // Hard settlement failure (no confirmed tx): re-challenge.
  const paymentRequired = buildPaymentRequired({
    resourceUrl,
    description,
    error: settleResult?.errorReason || 'settlement_failed',
    amountAtomic: priceAtomic
  });
  return respond(paymentRequired, 402, {
    ...paymentResponseHeader(settleResult ?? {}),
    'PAYMENT-REQUIRED': base64EncodeUtf8(JSON.stringify(paymentRequired))
  });
}

/**
 * Interpret a settle response under OKX syncSettle semantics and, when the tx
 * is broadcast but unconfirmed (pending/timeout), poll settle/status until it
 * confirms or the poll budget runs out.
 *
 * @returns { state: 'settled'|'pending'|'failed', settleResponse }
 */
async function resolveSettlement(env, settleResult) {
  if (!settleResult) return { state: 'failed', settleResponse: {} };

  // Only an explicit on-chain confirmation counts as settled. A bare
  // success:true without the OKX status extension is also final per
  // x402-core settleResponseSchema (status is optional).
  if (settleResult.success === true
    && (settleResult.status === undefined || settleResult.status === 'success')) {
    return { state: 'settled', settleResponse: settleResult };
  }

  // pending = broadcast, unconfirmed; timeout = confirmation timed out.
  // Both leave a real tx in flight: poll instead of failing or delivering.
  if ((settleResult.status === 'pending' || settleResult.status === 'timeout') && settleResult.transaction) {
    const polled = await pollSettleStatus(env, settleResult.transaction);
    if (polled === 'success') {
      return {
        state: 'settled',
        settleResponse: { ...settleResult, success: true, status: 'success' }
      };
    }
    if (polled === 'failed') {
      return { state: 'failed', settleResponse: settleResult };
    }
    return {
      state: 'pending',
      settleResponse: { ...settleResult, success: false, status: 'pending' }
    };
  }

  return { state: 'failed', settleResponse: settleResult };
}

/** Buyer replays a payment whose tx was still confirming. Poll status again:
 * confirmed → deliver (no second settle, nonce already spent); still pending →
 * another 402 pending notice; failed on-chain → clear receipt, ask to re-pay. */
async function resolvePendingReceipt(env, receiptKey, receipt, { deliver, respond, requirements }) {
  const polled = await pollSettleStatus(env, receipt.txHash);
  if (polled === 'success') {
    const settleResponse = { ...receipt.settleResponse, success: true, status: 'success' };
    receiptCache.set(receiptKey, { ...receipt, status: 'success', settleResponse, storedAt: Date.now() });
    return deliverPayload(deliver, respond, settleResponse);
  }
  if (polled === 'failed') {
    receiptCache.delete(receiptKey);
    return respond({
      error: 'settlement_failed',
      message: 'The on-chain transaction for this payment failed. A new payment is required.',
      transaction: receipt.txHash,
      network: requirements.network
    }, 402, paymentResponseHeader({ ...receipt.settleResponse, success: false }));
  }
  return pendingTxResponse(respond, receipt.settleResponse);
}

async function deliverPayload(deliver, respond, settleResponse) {
  let payload;
  try {
    payload = await deliver();
  } catch (error) {
    return respond({
      error: 'internal_error',
      message: error instanceof Error ? error.message : String(error)
    }, 500);
  }
  return respond(payload, 200, paymentResponseHeader(settleResponse));
}

function pendingTxResponse(respond, settleResponse) {
  return respond({
    error: 'settlement_pending',
    status: 'pending_tx',
    message: 'Payment transaction is broadcast but not yet confirmed on-chain. Data is withheld until confirmation.',
    transaction: settleResponse.transaction,
    network: settleResponse.network || X402_NETWORK,
    retry: {
      retry_with_same_payment: true,
      hint: 'Re-send the exact same request with the identical PAYMENT header. The service will check on-chain status and deliver the data without charging again.'
    }
  }, 402, paymentResponseHeader(settleResponse));
}

function paymentResponseHeader(settleResponse) {
  return { 'PAYMENT-RESPONSE': base64EncodeUtf8(JSON.stringify(settleResponse ?? {})) };
}

/** Same matching semantics as x402ResourceServer.findMatchingRequirements:
 * base fields must deep-equal; every server `extra` key must match buyer's. */
function requirementsMatch(serverReq, buyerAccepted) {
  const { extra: serverExtra, ...serverBase } = serverReq;
  const { extra: buyerExtra, ...buyerBase } = buyerAccepted ?? {};
  if (!deepEqual(serverBase, buyerBase)) return false;
  if (!serverExtra && !buyerExtra) return true;
  if (!serverExtra) return true;
  if (!buyerExtra) return false;
  for (const [key, value] of Object.entries(serverExtra)) {
    if (!deepEqual(buyerExtra[key], value)) return false;
  }
  return true;
}

function deepEqual(a, b) {
  return canonicalJson(a) === canonicalJson(b);
}

function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) {
    return `[${value.map((item) => canonicalJson(item)).join(',')}]`;
  }
  const keys = Object.keys(value).sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

class FacilitatorError extends Error {
  constructor(kind, detail) {
    super(kind);
    this.name = 'FacilitatorError';
    this.kind = kind; // generic machine-readable code, safe to expose
    this.detail = detail; // full detail, logs only — never sent to clients
  }
}

function facilitatorErrorResponse(respond, operation, error) {
  // Log full detail server-side; respond with generic codes only (no OKX body
  // excerpts or upstream internals leak to buyers).
  console.warn(`[x402] facilitator ${operation} error:`, error?.detail || error?.message || error);
  return respond({
    error: 'facilitator_error',
    operation,
    code: error instanceof FacilitatorError ? error.kind : 'facilitator_unreachable'
  }, 502);
}

/**
 * Signed request to the OKX hosted facilitator.
 * Mirrors OKXFacilitatorClient: prehash = timestamp + method + path + body,
 * HMAC-SHA256(secret) base64. `path` must include the query string when present.
 * Unwraps the OKX { code, msg, data } envelope and treats code !== "0" as a
 * business error even when HTTP status is 200.
 */
export async function facilitatorRequest(env, method, path, bodyObj) {
  const apiKey = env?.OKX_API_KEY;
  const secretKey = env?.OKX_SECRET_KEY;
  const passphrase = env?.OKX_PASSPHRASE;
  if (!apiKey || !secretKey || !passphrase) {
    throw new FacilitatorError('credentials_missing',
      'OKX facilitator credentials are not configured (OKX_API_KEY / OKX_SECRET_KEY / OKX_PASSPHRASE)');
  }

  const body = bodyObj === undefined || bodyObj === null ? '' : JSON.stringify(bodyObj);
  const timestamp = new Date().toISOString();
  const sign = await hmacSha256Base64(secretKey, timestamp + method + path + body);

  const response = await fetch(FACILITATOR_BASE_URL + path, {
    method,
    headers: {
      'OK-ACCESS-KEY': apiKey,
      'OK-ACCESS-SIGN': sign,
      'OK-ACCESS-TIMESTAMP': timestamp,
      'OK-ACCESS-PASSPHRASE': passphrase,
      'Content-Type': 'application/json'
    },
    ...(body ? { body } : {})
  });

  const text = await response.text();
  const endpoint = `${method} ${path.split('?')[0]}`;
  if (!response.ok) {
    throw new FacilitatorError(`okx_http_${response.status}`,
      `OKX facilitator ${endpoint} failed (${response.status}): ${excerpt(text)}`);
  }
  let json;
  try {
    json = JSON.parse(text);
  } catch {
    throw new FacilitatorError('okx_invalid_json',
      `OKX facilitator ${endpoint} returned invalid JSON: ${excerpt(text)}`);
  }
  if (json && typeof json === 'object' && 'code' in json) {
    if (String(json.code) !== '0') {
      throw new FacilitatorError(`okx_business_${json.code}`,
        `OKX facilitator ${endpoint} business error code=${json.code}: ${excerpt(json.msg ?? '')}`);
    }
    return json.data;
  }
  return json;
}

/** Poll GET settle/status until success/failed or the poll budget is spent.
 * @returns 'success' | 'failed' | 'pending' */
async function pollSettleStatus(env, txHash) {
  const budgetMs = positiveInt(env?.X402_SETTLE_POLL_BUDGET_MS, DEFAULT_SETTLE_POLL_BUDGET_MS);
  const intervalMs = positiveInt(env?.X402_SETTLE_POLL_INTERVAL_MS, DEFAULT_SETTLE_POLL_INTERVAL_MS);
  const deadline = Date.now() + budgetMs;
  for (;;) {
    try {
      const status = await facilitatorRequest(
        env,
        'GET',
        `/api/v6/pay/x402/settle/status?txHash=${encodeURIComponent(txHash)}`
      );
      if (status?.success === false) return 'failed';
      if (status?.status === 'success') return 'success';
    } catch (error) {
      // transient facilitator error — keep polling until the deadline
      console.warn('[x402] settle/status poll error:', error?.detail || error?.message || error);
    }
    const remaining = deadline - Date.now();
    if (remaining <= 0) return 'pending';
    await new Promise((resolve) => setTimeout(resolve, Math.min(intervalMs, remaining)));
  }
}

function positiveInt(value, fallback) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function pruneReceipts() {
  const now = Date.now();
  for (const [key, receipt] of receiptCache) {
    if (now - receipt.storedAt > RECEIPT_TTL_MS) receiptCache.delete(key);
  }
}

async function sha256Hex(text) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function hmacSha256Base64(secret, message) {
  const key = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );
  const signature = await crypto.subtle.sign('HMAC', key, new TextEncoder().encode(message));
  return base64FromBytes(new Uint8Array(signature));
}

function base64FromBytes(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64EncodeUtf8(text) {
  return base64FromBytes(new TextEncoder().encode(text));
}

function base64DecodeUtf8(base64) {
  const binary = atob(base64.trim());
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder('utf-8').decode(bytes);
}

function excerpt(text, limit = 200) {
  const compact = String(text ?? '').trim().replace(/\s+/g, ' ');
  if (!compact) return '<empty response>';
  return compact.length <= limit ? compact : `${compact.slice(0, limit - 3)}...`;
}
