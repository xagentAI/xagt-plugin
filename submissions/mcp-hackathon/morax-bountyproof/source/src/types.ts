export interface ParsedIssueUrl {
  owner: string;
  repo: string;
  number: number;
  canonicalUrl: string;
}

export interface GitHubLabel {
  name: string;
}

export interface GitHubUser {
  login: string;
}

export interface GitHubRepository {
  full_name: string;
  html_url: string;
  description: string | null;
  fork: boolean;
  archived: boolean;
  disabled: boolean;
  stargazers_count: number;
  forks_count: number;
  open_issues_count: number;
  created_at: string;
  updated_at: string;
  pushed_at: string | null;
  default_branch: string;
  owner: GitHubUser;
  source?: {
    full_name: string;
    html_url: string;
  };
}

export interface GitHubIssue {
  number: number;
  title: string;
  body: string | null;
  html_url: string;
  state: "open" | "closed";
  state_reason: string | null;
  locked: boolean;
  comments: number;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
  labels: GitHubLabel[];
  assignees: GitHubUser[];
  user: GitHubUser;
  author_association: string;
  pull_request?: unknown;
}

export interface GitHubTimelineEvent {
  event?: string;
  created_at?: string;
  actor?: GitHubUser;
  author_association?: string;
  source?: {
    issue?: {
      number?: number;
      title?: string;
      html_url?: string;
      state?: string;
      repository_url?: string;
      pull_request?: {
        html_url?: string;
        merged_at?: string | null;
      };
    };
  };
}

export interface CompetingPullRequest {
  number: number | null;
  title: string;
  url: string;
  state: string;
  createdAt: string | null;
}

export interface PayoutSignals {
  advertisedUsd: number[];
  advertisedTokens: string[];
  platformSignals: string[];
  status: "NO_MONETARY_SIGNAL" | "ADVERTISED_ONLY";
  escrowVerified: false;
}

export interface PromptSafetyFlag {
  code: string;
  severity: "medium" | "high";
  message: string;
}

export interface PreflightReason {
  severity: "info" | "warning" | "stop";
  code: string;
  message: string;
  evidenceUrl: string;
}

export type PreflightVerdict = "STOP" | "HOLD" | "PROCEED_TO_MAINTAINER_CONFIRMATION";

export interface BountyPreflight {
  schemaVersion: 1;
  checkedAt: string;
  requestId: string;
  verdict: PreflightVerdict;
  analysisConfidence: number;
  summary: string;
  input: ParsedIssueUrl & {
    expectedRewardUsd: number | null;
    expectedPlatform: string | null;
  };
  repository: {
    fullName: string;
    url: string;
    description: string | null;
    fork: boolean;
    upstream: string | null;
    archived: boolean;
    disabled: boolean;
    stars: number;
    forks: number;
    createdAt: string;
    pushedAt: string | null;
    pushAgeDays: number | null;
  };
  issue: {
    number: number;
    title: string;
    url: string;
    state: string;
    stateReason: string | null;
    locked: boolean;
    author: string;
    assignees: string[];
    comments: number;
    createdAt: string;
    updatedAt: string;
  };
  competition: {
    openCrossReferencedPullRequests: CompetingPullRequest[];
  };
  maintainerActivity: {
    timelineCommentCount: number;
    latestCommentAt: string | null;
  };
  payout: PayoutSignals;
  promptSafety: {
    issueContentTreatedAsUntrusted: true;
    flags: PromptSafetyFlag[];
  };
  reasons: PreflightReason[];
  nextActions: string[];
  limitations: string[];
  upstreamRateLimit: {
    limit: number | null;
    remaining: number | null;
    resetAt: string | null;
  };
}
