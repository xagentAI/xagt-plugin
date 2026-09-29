import type { ParsedIssueUrl } from "./parse-issue-url.js";
import { TtlCache } from "../lib/cache.js";
import { GitHubApiError, readGitHubRateLimit } from "./errors.js";
import type {
  NormalizedIssue,
  NormalizedIssueComment,
  NormalizedIssueContext,
  NormalizedRepositoryMetadata,
} from "./normalize.js";
import {
  normalizeIssueCommentsResponse,
  normalizeIssueResponse,
  normalizeRepositoryLanguagesResponse,
  normalizeRepositoryResponse,
} from "./normalize.js";

/** Repository coordinates shared by repository metadata requests. */
export type RepositoryCoordinates = Pick<ParsedIssueUrl, "owner" | "repo">;

/** Runtime settings for the read-only GitHub REST client. */
export type GitHubClientOptions = {
  token?: string;
  timeoutMs: number;
  cacheTtlMs?: number;
};

/** Optional request metadata used for safe, correlated logging. */
export type GitHubRequestContext = {
  requestId?: string;
};

/** Injectable transport keeps GitHub request tests fast and offline. */
export type GitHubFetch = typeof globalThis.fetch;

/**
 * Boundary between GitHub's REST API and the rest of BountyLens.
 *
 * Implementations must return normalized data so downstream scoring never
 * depends on GitHub's larger, changeable response payloads.
 */
export interface GitHubClient {
  getIssueContext(
    target: ParsedIssueUrl,
    context?: GitHubRequestContext,
  ): Promise<NormalizedIssueContext>;

  getIssue(
    target: ParsedIssueUrl,
    context?: GitHubRequestContext,
  ): Promise<NormalizedIssue>;

  getIssueComments(
    target: ParsedIssueUrl,
    context?: GitHubRequestContext,
  ): Promise<NormalizedIssueComment[]>;

  getRepository(
    target: RepositoryCoordinates,
    context?: GitHubRequestContext,
  ): Promise<NormalizedRepositoryMetadata>;

  getRepositoryLanguages(
    target: RepositoryCoordinates,
    context?: GitHubRequestContext,
  ): Promise<Record<string, number>>;
}

/** Read-only GitHub REST client. Additional endpoints are added incrementally. */
export class GitHubRestClient implements GitHubClient {
  private readonly issueContextCache: TtlCache<string, Promise<NormalizedIssueContext>>;

  constructor(
    private readonly options: GitHubClientOptions,
    private readonly fetcher: GitHubFetch = globalThis.fetch,
  ) {
    this.issueContextCache = new TtlCache(options.cacheTtlMs ?? 300_000);
  }

  private async getJson(endpoint: URL, resourceName: string): Promise<unknown> {
    const headers = new Headers({
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
    });

    // The token stays server-side and is never included in errors or logs.
    if (this.options.token !== undefined) {
      headers.set("Authorization", `Bearer ${this.options.token}`);
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), this.options.timeoutMs);
    let response: Response;

    try {
      response = await this.fetcher(endpoint, {
        method: "GET",
        headers,
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) {
        throw new GitHubApiError(
          "GITHUB_TIMEOUT",
          `GitHub ${resourceName} request timed out.`,
        );
      }

      throw new GitHubApiError(
        "GITHUB_NETWORK_ERROR",
        `GitHub ${resourceName} request could not be completed.`,
      );
    } finally {
      clearTimeout(timeout);
    }

    if (!response.ok) {
      const rateLimit = readGitHubRateLimit(response.headers);

      if (response.status === 429 || (response.status === 403 && rateLimit.remaining === 0)) {
        throw new GitHubApiError(
          "GITHUB_RATE_LIMITED",
          "GitHub API rate limit reached. Try again after the reset time.",
          { status: response.status, rateLimit },
        );
      }

      if (response.status === 404) {
        throw new GitHubApiError(
          "GITHUB_NOT_FOUND",
          `GitHub ${resourceName} was not found or is not public.`,
          { status: response.status },
        );
      }

      if (response.status === 403) {
        throw new GitHubApiError(
          "GITHUB_FORBIDDEN",
          `GitHub denied access to the ${resourceName}.`,
          { status: response.status },
        );
      }

      throw new GitHubApiError(
        "GITHUB_UPSTREAM_ERROR",
        `GitHub ${resourceName} request failed with status ${response.status}.`,
        { status: response.status },
      );
    }

    try {
      return await response.json();
    } catch {
      throw new GitHubApiError(
        "GITHUB_INVALID_RESPONSE",
        `GitHub returned an invalid ${resourceName} response.`,
        { status: response.status },
      );
    }
  }

  /** Fetch and normalize one public GitHub issue. */
  async getIssue(target: ParsedIssueUrl): Promise<NormalizedIssue> {
    const endpoint = new URL(
      `/repos/${encodeURIComponent(target.owner)}/${encodeURIComponent(target.repo)}/issues/${target.issueNumber}`,
      "https://api.github.com",
    );

    return normalizeIssueResponse(await this.getJson(endpoint, "issue"));
  }

  /** Fetch up to 100 public comments for one GitHub issue. */
  async getIssueComments(target: ParsedIssueUrl): Promise<NormalizedIssueComment[]> {
    const endpoint = new URL(
      `/repos/${encodeURIComponent(target.owner)}/${encodeURIComponent(target.repo)}/issues/${target.issueNumber}/comments`,
      "https://api.github.com",
    );
    endpoint.searchParams.set("per_page", "100");

    return normalizeIssueCommentsResponse(await this.getJson(endpoint, "issue comments"));
  }

  /** Fetch the repository metadata used by activity scoring. */
  async getRepository(target: RepositoryCoordinates): Promise<NormalizedRepositoryMetadata> {
    const endpoint = new URL(
      `/repos/${encodeURIComponent(target.owner)}/${encodeURIComponent(target.repo)}`,
      "https://api.github.com",
    );

    return normalizeRepositoryResponse(await this.getJson(endpoint, "repository"));
  }

  /** Fetch the language byte counts used for developer-fit scoring. */
  async getRepositoryLanguages(target: RepositoryCoordinates): Promise<Record<string, number>> {
    const endpoint = new URL(
      `/repos/${encodeURIComponent(target.owner)}/${encodeURIComponent(target.repo)}/languages`,
      "https://api.github.com",
    );

    return normalizeRepositoryLanguagesResponse(
      await this.getJson(endpoint, "repository languages"),
    );
  }

  private async loadIssueContext(target: ParsedIssueUrl): Promise<NormalizedIssueContext> {
    const [issue, comments, repositoryMetadata, languages] = await Promise.all([
      this.getIssue(target),
      this.getIssueComments(target),
      this.getRepository(target),
      this.getRepositoryLanguages(target),
    ]);

    return {
      issue,
      comments,
      repository: {
        ...repositoryMetadata,
        languages,
      },
    };
  }

  /** Build or reuse the provider-independent context consumed by extractors. */
  async getIssueContext(target: ParsedIssueUrl): Promise<NormalizedIssueContext> {
    const cacheKey = `${target.owner.toLowerCase()}/${target.repo.toLowerCase()}#${target.issueNumber}`;
    const cached = this.issueContextCache.get(cacheKey);

    if (cached !== undefined) {
      return cached;
    }

    // Cache the in-flight promise so concurrent evaluations share four GitHub
    // requests instead of multiplying them. Failed loads are never retained.
    const pending = this.loadIssueContext(target);
    this.issueContextCache.set(cacheKey, pending);

    try {
      return await pending;
    } catch (error) {
      if (this.issueContextCache.get(cacheKey) === pending) {
        this.issueContextCache.delete(cacheKey);
      }
      throw error;
    }
  }
}
