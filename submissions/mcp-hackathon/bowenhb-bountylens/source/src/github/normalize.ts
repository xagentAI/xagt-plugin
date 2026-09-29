import { z } from "zod";

/** Internal issue shape consumed by extractors and scoring code. */
export type NormalizedIssue = {
  title: string;
  body: string;
  state: "open" | "closed";
  labels: string[];
  assignees: string[];
  author: string;
  createdAt: string;
  updatedAt: string;
};

/** Minimal comment data needed to find public evidence and competition signals. */
export type NormalizedIssueComment = {
  author: string;
  body: string;
  createdAt: string;
  authorAssociation?: string;
};

/** Repository fields returned by GitHub's repository details endpoint. */
export type NormalizedRepositoryMetadata = {
  fullName: string;
  pushedAt: string | null;
  updatedAt: string;
  openIssuesCount: number;
};

/** Repository metadata used for activity and developer-fit scoring. */
export type NormalizedRepository = NormalizedRepositoryMetadata & {
  languages: Record<string, number>;
};

/** Provider-independent input for the BountyLens evidence extractors. */
export type NormalizedIssueContext = {
  issue: NormalizedIssue;
  comments: NormalizedIssueComment[];
  repository: NormalizedRepository;
};

const githubIssuePayloadSchema = z.object({
  title: z.string(),
  body: z.string().nullable(),
  state: z.enum(["open", "closed"]),
  labels: z.array(
    z.union([
      z.string(),
      z.object({
        name: z.string().nullable(),
      }),
    ]),
  ),
  assignees: z.array(z.object({ login: z.string() })).nullable(),
  user: z.object({ login: z.string() }).nullable(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  pull_request: z.unknown().optional(),
});

const githubIssueCommentPayloadSchema = z.object({
  user: z.object({ login: z.string() }).nullable(),
  body: z.string().nullable(),
  created_at: z.string().datetime({ offset: true }),
  author_association: z.string().optional(),
});

const githubIssueCommentsPayloadSchema = z.array(githubIssueCommentPayloadSchema);

const githubRepositoryPayloadSchema = z.object({
  full_name: z.string().min(1),
  pushed_at: z.string().datetime({ offset: true }).nullable(),
  updated_at: z.string().datetime({ offset: true }),
  open_issues_count: z.number().int().nonnegative(),
});

const githubRepositoryLanguagesPayloadSchema = z.record(
  z.string().min(1),
  z.number().int().nonnegative(),
);

/** Validate and minimize one GitHub issue response before it enters the app. */
export function normalizeIssueResponse(payload: unknown): NormalizedIssue {
  const issue = githubIssuePayloadSchema.parse(payload);

  // GitHub's issues endpoint also returns pull requests. BountyLens evaluates
  // issues only, so a PR-shaped response must not silently enter the pipeline.
  if (issue.pull_request !== undefined) {
    throw new Error("The GitHub resource is a pull request, not an issue.");
  }

  const labels = issue.labels.flatMap((label) => {
    const name = typeof label === "string" ? label : label.name;
    return name === null ? [] : [name];
  });

  return {
    title: issue.title,
    body: issue.body ?? "",
    state: issue.state,
    labels,
    assignees: (issue.assignees ?? []).map((assignee) => assignee.login),
    author: issue.user?.login ?? "ghost",
    createdAt: issue.created_at,
    updatedAt: issue.updated_at,
  };
}

/** Validate and minimize a GitHub issue-comments response. */
export function normalizeIssueCommentsResponse(payload: unknown): NormalizedIssueComment[] {
  return githubIssueCommentsPayloadSchema.parse(payload).map((comment) => {
    const normalized = {
      author: comment.user?.login ?? "ghost",
      body: comment.body ?? "",
      createdAt: comment.created_at,
    };

    return comment.author_association === undefined
      ? normalized
      : { ...normalized, authorAssociation: comment.author_association };
  });
}

/** Validate and minimize a GitHub repository-details response. */
export function normalizeRepositoryResponse(payload: unknown): NormalizedRepositoryMetadata {
  const repository = githubRepositoryPayloadSchema.parse(payload);

  return {
    fullName: repository.full_name,
    pushedAt: repository.pushed_at,
    updatedAt: repository.updated_at,
    openIssuesCount: repository.open_issues_count,
  };
}

/** Validate GitHub's language-to-byte-count response. */
export function normalizeRepositoryLanguagesResponse(payload: unknown): Record<string, number> {
  return githubRepositoryLanguagesPayloadSchema.parse(payload);
}
