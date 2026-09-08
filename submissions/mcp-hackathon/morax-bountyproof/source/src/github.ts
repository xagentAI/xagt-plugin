import { parseIssueUrl } from "./analyzer.js";
import type { GitHubIssue, GitHubRepository, GitHubTimelineEvent } from "./types.js";

const GITHUB_API = "https://api.github.com";
const API_VERSION = "2022-11-28";
const TIMEOUT_MS = 8_000;

interface RateLimitSnapshot {
  limit: number | null;
  remaining: number | null;
  resetAt: string | null;
}

interface GithubResult<T> {
  data: T;
  rateLimit: RateLimitSnapshot;
}

export class GitHubApiError extends Error {
  readonly status: number;
  readonly upstreamCode: string;

  constructor(status: number, upstreamCode: string, message: string) {
    super(message);
    this.name = "GitHubApiError";
    this.status = status;
    this.upstreamCode = upstreamCode;
  }
}

function parseInteger(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) ? parsed : null;
}

function rateLimitFrom(response: Response): RateLimitSnapshot {
  const resetSeconds = parseInteger(response.headers.get("x-ratelimit-reset"));
  return {
    limit: parseInteger(response.headers.get("x-ratelimit-limit")),
    remaining: parseInteger(response.headers.get("x-ratelimit-remaining")),
    resetAt: resetSeconds === null ? null : new Date(resetSeconds * 1_000).toISOString(),
  };
}

async function githubJson<T>(path: string, token?: string): Promise<GithubResult<T>> {
  const headers: Record<string, string> = {
    accept: "application/vnd.github+json",
    "user-agent": "BountyProof/0.1 (+https://github.com/fzlzjerry/bountyproof)",
    "x-github-api-version": API_VERSION,
  };
  if (token) headers.authorization = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(`${GITHUB_API}${path}`, {
      headers,
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    const message = error instanceof Error && error.name === "TimeoutError"
      ? "GitHub did not respond before the upstream timeout."
      : "GitHub could not be reached.";
    throw new GitHubApiError(502, "GITHUB_UNREACHABLE", message);
  }

  const rateLimit = rateLimitFrom(response);
  if (!response.ok) {
    let upstreamMessage = "GitHub rejected the request.";
    try {
      const body = (await response.json()) as { message?: string };
      if (body.message) upstreamMessage = body.message.slice(0, 300);
    } catch {
      // Keep the bounded generic message when GitHub returns a non-JSON error page.
    }
    const code = response.status === 404
      ? "GITHUB_NOT_FOUND"
      : response.status === 403 || response.status === 429
        ? "GITHUB_RATE_LIMITED"
        : "GITHUB_UPSTREAM_ERROR";
    throw new GitHubApiError(response.status, code, upstreamMessage);
  }

  return { data: (await response.json()) as T, rateLimit };
}

function mergeRateLimits(results: RateLimitSnapshot[]): RateLimitSnapshot {
  const limits = results.map(({ limit }) => limit).filter((value): value is number => value !== null);
  const remaining = results
    .map((entry) => entry.remaining)
    .filter((value): value is number => value !== null);
  const resets = results.map(({ resetAt }) => resetAt).filter((value): value is string => value !== null);
  return {
    limit: limits.length ? Math.min(...limits) : null,
    remaining: remaining.length ? Math.min(...remaining) : null,
    resetAt: resets.sort().at(-1) ?? null,
  };
}

export async function fetchIssueEvidence(issueUrl: string, token?: string) {
  const { owner, repo, number } = parseIssueUrl(issueUrl);
  const root = `/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}`;
  const [repository, issue, timeline] = await Promise.all([
    githubJson<GitHubRepository>(root, token),
    githubJson<GitHubIssue>(`${root}/issues/${number}`, token),
    githubJson<GitHubTimelineEvent[]>(`${root}/issues/${number}/timeline?per_page=100`, token),
  ]);

  return {
    repository: repository.data,
    issue: issue.data,
    timeline: timeline.data,
    rateLimit: mergeRateLimits([
      repository.rateLimit,
      issue.rateLimit,
      timeline.rateLimit,
    ]),
  };
}
