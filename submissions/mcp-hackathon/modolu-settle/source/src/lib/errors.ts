/**
 * Typed application errors and the public API error envelope.
 *
 * Services and domain code throw `AppError`; route handlers (via
 * `src/lib/http.ts`) are the only place that maps them to HTTP responses.
 * Raw SQL, driver, viem, or provider errors must never reach a client — wrap
 * them in an `AppError` with a stable code (ARCHITECTURE.md §9, §11).
 */

/** Stable error codes and their HTTP status (ARCHITECTURE.md §9). */
export const ERROR_CODES = {
  VALIDATION_ERROR: 400,
  INVALID_ADDRESS: 400,
  UNSUPPORTED_CHAIN: 400,
  UNSUPPORTED_ASSET: 400,
  INTENT_NOT_FOUND: 404,
  RATE_LIMITED: 429,
  UPSTREAM_UNAVAILABLE: 503,
  UPSTREAM_INVALID_RESPONSE: 502,
  INTERNAL_ERROR: 500,
} as const;

export type ErrorCode = keyof typeof ERROR_CODES;

/** Whether a client should retry the same request unchanged, by default. */
const RETRYABLE_BY_DEFAULT: Readonly<Record<ErrorCode, boolean>> = {
  VALIDATION_ERROR: false,
  INVALID_ADDRESS: false,
  UNSUPPORTED_CHAIN: false,
  UNSUPPORTED_ASSET: false,
  INTENT_NOT_FOUND: false,
  RATE_LIMITED: true,
  UPSTREAM_UNAVAILABLE: true,
  UPSTREAM_INVALID_RESPONSE: false,
  INTERNAL_ERROR: false,
};

export interface AppErrorOptions {
  readonly retryable?: boolean;
  readonly cause?: unknown;
  /** Internal diagnostic fields for logs only; never sent to clients. */
  readonly context?: Readonly<Record<string, unknown>>;
}

export class AppError extends Error {
  readonly code: ErrorCode;
  readonly httpStatus: number;
  readonly retryable: boolean;
  readonly context: Readonly<Record<string, unknown>>;

  constructor(code: ErrorCode, message: string, options: AppErrorOptions = {}) {
    super(message, options.cause === undefined ? undefined : { cause: options.cause });
    this.name = "AppError";
    this.code = code;
    this.httpStatus = ERROR_CODES[code];
    this.retryable = options.retryable ?? RETRYABLE_BY_DEFAULT[code];
    this.context = options.context ?? {};
  }
}

export function isAppError(value: unknown): value is AppError {
  return value instanceof AppError;
}

/**
 * Coerces any thrown value into an `AppError`. Unknown errors become a generic
 * `INTERNAL_ERROR` so that internal messages never leak; the original is kept
 * as `cause` for logging.
 */
export function toAppError(error: unknown): AppError {
  if (isAppError(error)) {
    return error;
  }
  return new AppError("INTERNAL_ERROR", "Unexpected internal error", { cause: error });
}

/** The top-level error object every failed API response carries. */
export interface ErrorEnvelope {
  readonly error: {
    readonly code: ErrorCode;
    readonly message: string;
    readonly retryable: boolean;
  };
}

export function toErrorEnvelope(error: AppError): ErrorEnvelope {
  return {
    error: {
      code: error.code,
      message: error.message,
      retryable: error.retryable,
    },
  };
}
