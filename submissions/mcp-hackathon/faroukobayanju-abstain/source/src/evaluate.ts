/**
 * One evaluation, end to end.
 *
 *   fetchAll ──▶ build GateInput ──▶ runGate ──▶ appendReceipt ──▶ respond
 *      │                                              │
 *      └─ resolves as_of from coverage                └─ atomic CAS, no fork
 *
 * The receipt is written BEFORE responding, so there is no state where a caller
 * believes it was authorized but the chain has no record of it.
 */
import { runGate } from './gate/index.js';
import { fetchAll, type TtlCache } from './nexus/fetch-all.js';
import type { NexusClient } from './nexus/client.js';
import { mergePolicy, policyHash, type PolicyName } from './policy/index.js';
import { inputsDigest, type Receipt, type ReceiptBody } from './receipt/schema.js';
import { appendReceipt, type ReceiptStore } from './store/types.js';
import type { Datum, GateInput, Policy, Proposal } from './types.js';

export interface EvaluateRequest {
  symbol: string;
  side: 'BUY' | 'SELL';
  notional: number;
  policy?: PolicyName;
}

export interface EvaluateDeps {
  client: NexusClient;
  store: ReceiptStore;
  cache: TtlCache;
  basePolicy: Policy;
  accountEquity: number;
  now?: () => number;
}

export class ValidationError extends Error {
  constructor(readonly field: string, message: string) {
    super(message);
    this.name = 'ValidationError';
  }
}

const SIDES = new Set(['BUY', 'SELL']);
const SYMBOL = /^[A-Z0-9]{1,20}\/[A-Z0-9]{1,20}$/;

export function validate(raw: unknown): EvaluateRequest {
  if (raw === null || typeof raw !== 'object') throw new ValidationError('body', 'body must be a JSON object');
  const b = raw as Record<string, unknown>;

  const symbol = b['symbol'];
  if (typeof symbol !== 'string' || !SYMBOL.test(symbol)) {
    throw new ValidationError('symbol', 'symbol must be an uppercase pair such as "BTC/USDT"');
  }
  const side = b['side'];
  if (typeof side !== 'string' || !SIDES.has(side)) {
    throw new ValidationError('side', 'side must be "BUY" or "SELL"');
  }
  const notional = b['notional'];
  if (typeof notional !== 'number' || !Number.isFinite(notional) || notional <= 0) {
    throw new ValidationError('notional', 'notional must be a positive finite number');
  }
  const policy = b['policy'];
  if (policy !== undefined && policy !== 'strict' && policy !== 'permissive') {
    throw new ValidationError('policy', 'policy must be "strict" or "permissive"');
  }
  if (b['signalId'] !== undefined) {
    throw new ValidationError('signalId', 'signalId is derived from the Nexus signal and cannot be supplied by callers');
  }

  return {
    symbol,
    side: side as 'BUY' | 'SELL',
    notional,
    ...(policy ? { policy: policy as PolicyName } : {}),
  };
}

/** Only the payloads that were actually readable contribute to the digest. */
function digestOf(data: Record<string, Datum<unknown>>): string {
  const payloads: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(data)) {
    payloads[k] = v.ok ? v.value : { unavailable: v.outcome };
  }
  return inputsDigest(payloads);
}

export interface EvaluateResult {
  receipt: Receipt;
  policyName: PolicyName;
}

export async function evaluate(req: EvaluateRequest, deps: EvaluateDeps): Promise<EvaluateResult> {
  const now = (deps.now ?? Date.now)();
  const policyName: PolicyName = req.policy ?? 'strict';
  const policy = mergePolicy(deps.basePolicy, policyName);

  const { asOf, data } = await fetchAll(deps.client, req.symbol, now, deps.cache);

  // Deriving the id from the signal itself means polling an unchanged signal
  // twice is a genuine duplicate, which is what replay protection should catch.
  const derivedId = data.signal.ok
    ? `sig_${req.symbol.replace('/', '-')}_${data.signal.value.timestamp}`
    : `sig_${req.symbol.replace('/', '-')}_unavailable_${now}`;

  const proposal: Proposal = {
    symbol: req.symbol,
    side: req.side,
    notional: req.notional,
    signalId: derivedId,
  };

  const priorReceipts = await deps.store.all();
  const seenSignalIds = new Set(priorReceipts.map((r) => r.signal_id));

  const input: GateInput = {
    asOf,
    now,
    proposal,
    data,
    seenSignalIds,
    accountEquity: deps.accountEquity,
  };

  const outcome = runGate(input, policy);

  const body: ReceiptBody = {
    ts: new Date(now).toISOString(),
    signal_id: proposal.signalId,
    as_of: asOf,
    policy_hash: policyHash(policy),
    inputs_digest: digestOf(data as unknown as Record<string, Datum<unknown>>),
    verdict: outcome.verdict,
    checks: outcome.checks,
    ...(outcome.reason ? { reason: outcome.reason } : {}),
  };

  return { receipt: await appendReceipt(deps.store, body, undefined, priorReceipts), policyName };
}
