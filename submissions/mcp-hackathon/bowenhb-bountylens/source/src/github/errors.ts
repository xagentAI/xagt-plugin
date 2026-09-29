export type GitHubErrorCode =
  | "GITHUB_FORBIDDEN"
  | "GITHUB_INVALID_RESPONSE"
  | "GITHUB_NETWORK_ERROR"
  | "GITHUB_NOT_FOUND"
  | "GITHUB_RATE_LIMITED"
  | "GITHUB_TIMEOUT"
  | "GITHUB_UPSTREAM_ERROR";

export type GitHubRateLimit = {
  limit: number | null;
  remaining: number | null;
  resetAt: string | null;
  retryAfterSeconds: number | null;
};

type GitHubApiErrorOptions = {
  status?: number;
  rateLimit?: GitHubRateLimit;
};

/** Safe, stable error returned by the GitHub integration boundary. */
export class GitHubApiError extends Error {
  readonly code: GitHubErrorCode;
  readonly status: number | undefined;
  readonly rateLimit: GitHubRateLimit | undefined;

  constructor(code: GitHubErrorCode, message: string, options: GitHubApiErrorOptions = {}) {
    super(message);
    this.name = "GitHubApiError";
    this.code = code;
    this.status = options.status;
    this.rateLimit = options.rateLimit;
  }
}

function parseNonNegativeInteger(value: string | null): number | null {
  if (value === null || !/^\d+$/.test(value)) {
    return null;
  }

  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

/** Read GitHub's quota metadata without trusting malformed header values. */
export function readGitHubRateLimit(headers: Headers): GitHubRateLimit {
  const resetEpochSeconds = parseNonNegativeInteger(headers.get("x-ratelimit-reset"));
  const resetDate =
    resetEpochSeconds === null ? null : new Date(resetEpochSeconds * 1_000);

  return {
    limit: parseNonNegativeInteger(headers.get("x-ratelimit-limit")),
    remaining: parseNonNegativeInteger(headers.get("x-ratelimit-remaining")),
    resetAt:
      resetDate !== null && Number.isFinite(resetDate.getTime()) ? resetDate.toISOString() : null,
    retryAfterSeconds: parseNonNegativeInteger(headers.get("retry-after")),
  };
}
