import type { GitHubIssue, GitHubRepository, GitHubTimelineEvent } from "../src/types.js";

export function repository(overrides: Partial<GitHubRepository> = {}): GitHubRepository {
  return {
    full_name: "example/project",
    html_url: "https://github.com/example/project",
    description: "A maintained example project",
    fork: false,
    archived: false,
    disabled: false,
    stargazers_count: 1_200,
    forks_count: 80,
    open_issues_count: 12,
    created_at: "2020-01-01T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
    pushed_at: "2026-09-07T00:00:00Z",
    default_branch: "main",
    owner: { login: "example" },
    ...overrides,
  };
}

export function issue(overrides: Partial<GitHubIssue> = {}): GitHubIssue {
  return {
    number: 42,
    title: "Add bounded export support [$100]",
    body: "Funded through Algora. Please discuss scope before opening a pull request.",
    html_url: "https://github.com/example/project/issues/42",
    state: "open",
    state_reason: null,
    locked: false,
    comments: 3,
    created_at: "2026-09-01T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
    closed_at: null,
    labels: [{ name: "bounty" }, { name: "$100" }],
    assignees: [],
    user: { login: "maintainer" },
    author_association: "MEMBER",
    ...overrides,
  };
}

export function evidence(overrides: {
  repository?: GitHubRepository;
  issue?: GitHubIssue;
  timeline?: GitHubTimelineEvent[];
} = {}) {
  return {
    repository: overrides.repository ?? repository(),
    issue: overrides.issue ?? issue(),
    timeline: overrides.timeline ?? [],
    rateLimit: { limit: 60, remaining: 57, resetAt: "2026-09-08T06:00:00.000Z" },
  };
}
