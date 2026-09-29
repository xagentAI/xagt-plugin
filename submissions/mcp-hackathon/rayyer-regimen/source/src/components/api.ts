import type { DemoEquityPoint } from '@/lib/demo-curve';
import type { SelfAttackReport } from '@/lib/engine/self-attack';
import type { SignificanceReport } from '@/lib/engine/significance';
import type { ErrorCode } from '@/lib/errors';

/**
 * The client side of the REST envelope.
 *
 * Success and failure share one shape on the wire, so there is one parser here and both
 * the server-rendered hero and the browser panel use it. The error branch keeps `code`,
 * `message` and `remedy` intact rather than flattening them into a generic string — the
 * remedy is the most useful sentence the API produces and throwing it away would be
 * replacing an answer with an apology.
 */

export interface ApiErrorBody {
  readonly code: ErrorCode | string;
  readonly message: string;
  readonly retryable?: boolean;
  readonly remedy?: string;
  readonly details?: Readonly<Record<string, unknown>>;
}

export interface EvaluatePayload {
  readonly report: SignificanceReport;
}

export interface SelfAttackPayload {
  readonly report: SelfAttackReport;
}

export type ApiResult<T> = { readonly ok: true; readonly data: T } | { readonly ok: false; readonly error: ApiErrorBody };

function asErrorBody(value: unknown): ApiErrorBody | null {
  if (typeof value !== 'object' || value === null) return null;
  const error = (value as { error?: unknown }).error;
  if (typeof error !== 'object' || error === null) return null;
  const { code, message } = error as { code?: unknown; message?: unknown };
  if (typeof code !== 'string' || typeof message !== 'string') return null;
  const { remedy, retryable, details } = error as {
    remedy?: unknown;
    retryable?: unknown;
    details?: unknown;
  };
  return {
    code,
    message,
    ...(typeof retryable === 'boolean' ? { retryable } : {}),
    ...(typeof remedy === 'string' ? { remedy } : {}),
    ...(typeof details === 'object' && details !== null ? { details: details as Record<string, unknown> } : {}),
  };
}

export async function postJson<T>(url: string, body: unknown, init: RequestInit = {}): Promise<ApiResult<T>> {
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
      ...init,
    });
  } catch (caught) {
    return {
      ok: false,
      error: {
        code: 'network_unreachable',
        message: caught instanceof Error && caught.name === 'TimeoutError' ? 'The request timed out.' : 'The request never reached Regimen.',
        retryable: true,
        remedy: 'Check the connection and run it again.',
      },
    };
  }

  let parsed: unknown;
  try {
    parsed = await response.json();
  } catch {
    return {
      ok: false,
      error: {
        code: 'upstream_malformed',
        message: `Regimen answered ${response.status} with a body that is not JSON.`,
        retryable: false,
      },
    };
  }

  const error = asErrorBody(parsed);
  if (error) return { ok: false, error };

  if (!response.ok) {
    return {
      ok: false,
      error: { code: 'internal', message: `Regimen answered ${response.status}.`, retryable: response.status >= 500 },
    };
  }

  const data = (parsed as { data?: unknown }).data;
  if (data === undefined) {
    return { ok: false, error: { code: 'upstream_malformed', message: 'The response carried no payload.', retryable: false } };
  }
  return { ok: true, data: data as T };
}

export interface EvaluateOptions {
  readonly bootstrapResamples?: number;
  readonly confidence?: number;
}

export function evaluateRequest(
  equity: ReadonlyArray<DemoEquityPoint>,
  label: string,
  options: EvaluateOptions = {},
) {
  return {
    selector: { source: 'inline', trackRecord: { label, equity } },
    options: { bootstrapResamples: options.bootstrapResamples ?? 2000, confidence: options.confidence ?? 0.95 },
  };
}

export function selfAttackRequest(equity: ReadonlyArray<DemoEquityPoint>, label: string, simulations: number) {
  return {
    selector: { source: 'inline', trackRecord: { label, equity } },
    options: { simulations },
  };
}
