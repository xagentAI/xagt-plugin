export type ErrorCode =
  | "AUTH_REQUIRED"
  | "AUTH_INVALID"
  | "KEY_EXPIRED"
  | "RATE_LIMITED"
  | "SCOPE_DENIED"
  | "INVALID_REQUEST"
  | "IDEMPOTENCY_REQUIRED"
  | "IDEMPOTENCY_CONFLICT"
  | "REQUEST_IN_PROGRESS"
  | "SOURCE_URL_BLOCKED"
  | "SOURCE_FETCH_FAILED"
  | "SOURCE_TOO_LARGE"
  | "SOURCE_INVALID_MIME"
  | "SOURCE_NEEDS_RENDERING"
  | "INSUFFICIENT_EVIDENCE"
  | "GENERATION_FAILED"
  | "EVIDENCE_VALIDATION_FAILED"
  | "QUALITY_VALIDATION_FAILED"
  | "MISSION_NOT_FOUND"
  | "METHOD_NOT_ALLOWED"
  | "INTERNAL_ERROR";

export class AppError extends Error {
  readonly code: ErrorCode;
  readonly status: number;
  readonly retryable: boolean;
  readonly details: Record<string, unknown> | undefined;

  constructor(
    code: ErrorCode,
    message: string,
    status: number,
    options: { retryable?: boolean; details?: Record<string, unknown> } = {},
  ) {
    super(message);
    this.name = "AppError";
    this.code = code;
    this.status = status;
    this.retryable = options.retryable ?? false;
    this.details = options.details;
  }
}

export function asAppError(error: unknown): AppError {
  if (error instanceof AppError) return error;
  return new AppError("INTERNAL_ERROR", "An unexpected error occurred.", 500, {
    retryable: true,
  });
}
