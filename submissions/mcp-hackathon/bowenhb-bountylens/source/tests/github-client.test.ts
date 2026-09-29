import { describe, expect, it, vi } from "vitest";

import { GitHubRestClient, type GitHubFetch } from "../src/github/client.js";
import { GitHubApiError } from "../src/github/errors.js";

const issueTarget = {
  owner: "openai",
  repo: "example",
  issueNumber: 42,
  canonicalUrl: "https://github.com/openai/example/issues/42",
};

const issuePayload = {
  title: "Document the public API",
  body: null,
  state: "open",
  labels: ["documentation", { name: "good first issue" }, { name: null }],
  assignees: [{ login: "octocat" }],
  user: { login: "maintainer" },
  created_at: "2026-09-01T08:00:00Z",
  updated_at: "2026-09-15T10:30:00Z",
};

describe("GitHubRestClient.getIssue", () => {
  it("requests the issue endpoint and returns a minimal normalized issue", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json(issuePayload, { status: 200 }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssue(issueTarget)).resolves.toEqual({
      title: "Document the public API",
      body: "",
      state: "open",
      labels: ["documentation", "good first issue"],
      assignees: ["octocat"],
      author: "maintainer",
      createdAt: "2026-09-01T08:00:00Z",
      updatedAt: "2026-09-15T10:30:00Z",
    });

    expect(fetcher).toHaveBeenCalledOnce();
    const [input, init] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toBe("https://api.github.com/repos/openai/example/issues/42");
    expect(init?.method).toBe("GET");
    expect(new Headers(init?.headers).get("Accept")).toBe("application/vnd.github+json");
    expect(new Headers(init?.headers).get("Authorization")).toBeNull();
  });

  it("fails without exposing the upstream response body when GitHub returns an error", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json({ message: "sensitive upstream details" }, { status: 404 }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssue(issueTarget)).rejects.toMatchObject({
      name: "GitHubApiError",
      code: "GITHUB_NOT_FOUND",
      status: 404,
      message: "GitHub issue was not found or is not public.",
    });
  });

  it("rejects pull requests returned by GitHub's issues endpoint", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json({ ...issuePayload, pull_request: { url: "https://api.github.com/pulls/42" } }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssue(issueTarget)).rejects.toThrow(
      "The GitHub resource is a pull request, not an issue.",
    );
  });

  it("adds a server-side token without changing the public request URL", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () => Response.json(issuePayload));
    const client = new GitHubRestClient(
      { timeoutMs: 10_000, token: "test-token-do-not-use" },
      fetcher,
    );

    await client.getIssue(issueTarget);

    const [input, init] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toBe("https://api.github.com/repos/openai/example/issues/42");
    expect(new Headers(init?.headers).get("Authorization")).toBe(
      "Bearer test-token-do-not-use",
    );
  });

  it("aborts a GitHub request after the configured timeout", async () => {
    const fetcher = vi.fn<GitHubFetch>(
      (_input, init) =>
        new Promise<Response>((_resolve, reject) => {
          const signal = init?.signal;

          if (signal === undefined || signal === null) {
            reject(new Error("Expected an abort signal."));
            return;
          }

          signal.addEventListener("abort", () => reject(signal.reason), { once: true });
        }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10 }, fetcher);

    await expect(client.getIssue(issueTarget)).rejects.toMatchObject({
      name: "GitHubApiError",
      code: "GITHUB_TIMEOUT",
    });
  });

  it.each([
    { status: 403, remaining: "0" },
    { status: 429, remaining: "12" },
  ])("maps a $status response to GITHUB_RATE_LIMITED", async ({ status, remaining }) => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json(
        { message: "API rate limit exceeded" },
        {
          status,
          headers: {
            "x-ratelimit-limit": "60",
            "x-ratelimit-remaining": remaining,
            "x-ratelimit-reset": "1800000000",
            "retry-after": "30",
          },
        },
      ),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssue(issueTarget)).rejects.toMatchObject({
      name: "GitHubApiError",
      code: "GITHUB_RATE_LIMITED",
      status,
      rateLimit: {
        limit: 60,
        remaining: Number(remaining),
        resetAt: new Date(1_800_000_000_000).toISOString(),
        retryAfterSeconds: 30,
      },
    });
  });

  it("distinguishes a permission failure from rate limiting", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json(
        { message: "Forbidden" },
        { status: 403, headers: { "x-ratelimit-remaining": "17" } },
      ),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssue(issueTarget)).rejects.toBeInstanceOf(GitHubApiError);
    await expect(client.getIssue(issueTarget)).rejects.toMatchObject({
      code: "GITHUB_FORBIDDEN",
      status: 403,
    });
  });
});

describe("GitHubRestClient.getIssueComments", () => {
  it("requests and normalizes up to 100 issue comments", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json([
        {
          user: { login: "maintainer" },
          body: "Please include a regression test.",
          created_at: "2026-09-15T11:00:00Z",
          author_association: "MEMBER",
        },
        {
          user: null,
          body: null,
          created_at: "2026-09-15T12:00:00Z",
        },
      ]),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssueComments(issueTarget)).resolves.toEqual([
      {
        author: "maintainer",
        body: "Please include a regression test.",
        createdAt: "2026-09-15T11:00:00Z",
        authorAssociation: "MEMBER",
      },
      {
        author: "ghost",
        body: "",
        createdAt: "2026-09-15T12:00:00Z",
      },
    ]);

    const [input] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toBe(
      "https://api.github.com/repos/openai/example/issues/42/comments?per_page=100",
    );
  });
});

describe("GitHubRestClient.getRepository", () => {
  it("requests and normalizes repository activity metadata", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json({
        full_name: "openai/example",
        pushed_at: "2026-09-14T07:30:00Z",
        updated_at: "2026-09-15T09:45:00Z",
        open_issues_count: 27,
        private: false,
        description: "This unneeded field is intentionally discarded.",
      }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getRepository(issueTarget)).resolves.toEqual({
      fullName: "openai/example",
      pushedAt: "2026-09-14T07:30:00Z",
      updatedAt: "2026-09-15T09:45:00Z",
      openIssuesCount: 27,
    });

    const [input] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toBe("https://api.github.com/repos/openai/example");
  });

  it("preserves a null pushed-at timestamp for an empty repository", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json({
        full_name: "openai/empty-example",
        pushed_at: null,
        updated_at: "2026-09-15T09:45:00Z",
        open_issues_count: 0,
      }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getRepository(issueTarget)).resolves.toMatchObject({ pushedAt: null });
  });
});

describe("GitHubRestClient.getRepositoryLanguages", () => {
  it("requests and validates repository language byte counts", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () =>
      Response.json({ TypeScript: 120_500, JavaScript: 9_250, Dockerfile: 830 }),
    );
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getRepositoryLanguages(issueTarget)).resolves.toEqual({
      TypeScript: 120_500,
      JavaScript: 9_250,
      Dockerfile: 830,
    });

    const [input] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toBe("https://api.github.com/repos/openai/example/languages");
  });

  it("accepts an empty language map for an empty repository", async () => {
    const fetcher = vi.fn<GitHubFetch>(async () => Response.json({}));
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getRepositoryLanguages(issueTarget)).resolves.toEqual({});
  });
});

describe("GitHubRestClient.getIssueContext", () => {
  it("combines four GitHub responses into one minimal internal context", async () => {
    const fetcher = vi.fn<GitHubFetch>(async (input) => {
      const url = new URL(String(input));

      switch (url.pathname) {
        case "/repos/openai/example/issues/42":
          return Response.json({ ...issuePayload, ignored_issue_field: "discard me" });
        case "/repos/openai/example/issues/42/comments":
          return Response.json([
            {
              user: { login: "contributor" },
              body: "I can work on this.",
              created_at: "2026-09-15T12:00:00Z",
              author_association: "CONTRIBUTOR",
              ignored_comment_field: "discard me",
            },
          ]);
        case "/repos/openai/example":
          return Response.json({
            full_name: "openai/example",
            pushed_at: "2026-09-14T07:30:00Z",
            updated_at: "2026-09-15T09:45:00Z",
            open_issues_count: 27,
            ignored_repository_field: "discard me",
          });
        case "/repos/openai/example/languages":
          return Response.json({ TypeScript: 120_500 });
        default:
          return Response.json({ message: "Unexpected test URL" }, { status: 500 });
      }
    });
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);
    const firstRequest = client.getIssueContext(issueTarget);
    const concurrentRequest = client.getIssueContext(issueTarget);

    await expect(firstRequest).resolves.toEqual({
      issue: {
        title: "Document the public API",
        body: "",
        state: "open",
        labels: ["documentation", "good first issue"],
        assignees: ["octocat"],
        author: "maintainer",
        createdAt: "2026-09-01T08:00:00Z",
        updatedAt: "2026-09-15T10:30:00Z",
      },
      comments: [
        {
          author: "contributor",
          body: "I can work on this.",
          createdAt: "2026-09-15T12:00:00Z",
          authorAssociation: "CONTRIBUTOR",
        },
      ],
      repository: {
        fullName: "openai/example",
        pushedAt: "2026-09-14T07:30:00Z",
        updatedAt: "2026-09-15T09:45:00Z",
        openIssuesCount: 27,
        languages: { TypeScript: 120_500 },
      },
    });
    await expect(concurrentRequest).resolves.toEqual(await firstRequest);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });

  it("does not retain a failed context load in the cache", async () => {
    let issueAttempts = 0;
    const fetcher = vi.fn<GitHubFetch>(async (input) => {
      const url = new URL(String(input));

      if (url.pathname === "/repos/openai/example/issues/42") {
        issueAttempts += 1;
        return issueAttempts === 1
          ? Response.json({ message: "Temporary failure" }, { status: 500 })
          : Response.json(issuePayload);
      }
      if (url.pathname === "/repos/openai/example/issues/42/comments") {
        return Response.json([]);
      }
      if (url.pathname === "/repos/openai/example/languages") {
        return Response.json({ TypeScript: 120_500 });
      }
      return Response.json({
        full_name: "openai/example",
        pushed_at: "2026-09-14T07:30:00Z",
        updated_at: "2026-09-15T09:45:00Z",
        open_issues_count: 27,
      });
    });
    const client = new GitHubRestClient({ timeoutMs: 10_000 }, fetcher);

    await expect(client.getIssueContext(issueTarget)).rejects.toMatchObject({
      code: "GITHUB_UPSTREAM_ERROR",
    });
    await expect(client.getIssueContext(issueTarget)).resolves.toMatchObject({
      issue: { title: "Document the public API" },
    });
    expect(issueAttempts).toBe(2);
  });
});
