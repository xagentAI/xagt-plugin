/**
 * One error vocabulary for the whole service.
 *
 * Every failure a caller can provoke maps to exactly one code here, and the code is
 * part of the public contract: an agent branches on `code`, a human reads `message`,
 * and `retryable` says whether trying again can possibly help. Nothing else leaks —
 * upstream bodies are summarised, never forwarded verbatim, because they can contain
 * account detail we have no business relaying.
 */

export const ERROR_CODES = [
  // Caller-side
  'invalid_input',
  'missing_credentials',
  'unsupported_source',
  'not_found',
  'rate_limited',

  // Evidence-side: the request was well formed, the data cannot support an answer
  'insufficient_sample',
  'coverage_gap',
  'undefined_statistic',

  // Upstream (OlaXBT Nexus or another data source)
  'upstream_unauthorized',
  'upstream_rejected',
  'upstream_not_published',
  'upstream_rate_limited',
  'upstream_unavailable',
  'upstream_timeout',
  'upstream_malformed',

  // Us
  'internal',
] as const;

export type ErrorCode = (typeof ERROR_CODES)[number];

const HTTP_STATUS: Record<ErrorCode, number> = {
  invalid_input: 400,
  missing_credentials: 401,
  unsupported_source: 400,
  not_found: 404,
  rate_limited: 429,

  insufficient_sample: 422,
  coverage_gap: 422,
  undefined_statistic: 422,

  upstream_unauthorized: 502,
  upstream_rejected: 502,
  upstream_not_published: 409,
  upstream_rate_limited: 503,
  upstream_unavailable: 503,
  upstream_timeout: 504,
  upstream_malformed: 502,

  internal: 500,
};

const RETRYABLE: ReadonlySet<ErrorCode> = new Set<ErrorCode>([
  'rate_limited',
  'upstream_rate_limited',
  'upstream_unavailable',
  'upstream_timeout',
]);

export interface RegimenErrorOptions {
  /** Structured, non-sensitive detail a caller can act on. */
  readonly details?: Readonly<Record<string, unknown>>;
  /** What the caller should do instead. Written for a model as much as a human. */
  readonly remedy?: string;
  readonly cause?: unknown;
}

export class RegimenError extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly retryable: boolean;
  readonly details?: Readonly<Record<string, unknown>>;
  readonly remedy?: string;

  constructor(code: ErrorCode, message: string, options: RegimenErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = 'RegimenError';
    this.code = code;
    this.status = HTTP_STATUS[code];
    this.retryable = RETRYABLE.has(code);
    if (options.details) this.details = options.details;
    if (options.remedy) this.remedy = options.remedy;
  }

  /** The wire shape. Identical for REST and for MCP tool errors. */
  toJSON() {
    return {
      error: {
        code: this.code,
        message: this.message,
        retryable: this.retryable,
        ...(this.remedy ? { remedy: this.remedy } : {}),
        ...(this.details ? { details: this.details } : {}),
      },
    } as const;
  }
}

export function isRegimenError(value: unknown): value is RegimenError {
  return value instanceof RegimenError;
}

/**
 * Normalise anything thrown into a RegimenError. An unrecognised throw becomes
 * `internal` with a generic message — we never surface a raw stack or upstream body.
 */
export function toRegimenError(value: unknown): RegimenError {
  if (isRegimenError(value)) return value;
  if (value instanceof Error && value.name === 'AbortError') {
    return new RegimenError('upstream_timeout', 'The upstream request timed out.', {
      cause: value,
      remedy: 'Retry. If it persists, reduce the requested range.',
    });
  }
  return new RegimenError('internal', 'An unexpected internal error occurred.', { cause: value });
}
