/** The normalized repository and issue coordinates used by GitHub API calls. */
export type ParsedIssueUrl = {
  owner: string;
  repo: string;
  issueNumber: number;
  canonicalUrl: string;
};

/** Stable application error used when an input is not a public GitHub issue URL. */
export class InvalidIssueUrlError extends Error {
  readonly code = "INVALID_ISSUE_URL";

  constructor(message = "A valid public GitHub issue URL is required.") {
    super(message);
    this.name = "InvalidIssueUrlError";
  }
}

const ownerPattern = /^[a-z0-9](?:[a-z0-9-]{0,37}[a-z0-9])?$/i;
const repositoryPattern = /^[a-z0-9._-]{1,100}$/i;
const issueNumberPattern = /^[1-9][0-9]*$/;

function decodePathSegment(segment: string): string {
  try {
    return decodeURIComponent(segment);
  } catch {
    throw new InvalidIssueUrlError("The GitHub issue URL contains invalid path encoding.");
  }
}

/**
 * Parse a browser-facing GitHub issue URL into coordinates for REST API calls.
 *
 * Query strings, fragments, and a trailing slash are accepted because they do
 * not change the referenced issue. Pull-request URLs and look-alike hosts are
 * rejected explicitly.
 */
export function parseIssueUrl(input: string): ParsedIssueUrl {
  let url: URL;

  try {
    url = new URL(input);
  } catch {
    throw new InvalidIssueUrlError();
  }

  if (
    url.protocol !== "https:" ||
    url.hostname.toLowerCase() !== "github.com" ||
    url.port !== "" ||
    url.username !== "" ||
    url.password !== ""
  ) {
    throw new InvalidIssueUrlError("Only public https://github.com issue URLs are supported.");
  }

  const segments = url.pathname.split("/").filter(Boolean).map(decodePathSegment);

  if (segments.length !== 4 || segments[2] !== "issues") {
    throw new InvalidIssueUrlError(
      "Expected a URL in the form https://github.com/{owner}/{repo}/issues/{number}.",
    );
  }

  const [owner, repo, , issueNumberText] = segments;

  if (
    owner === undefined ||
    repo === undefined ||
    issueNumberText === undefined ||
    !ownerPattern.test(owner) ||
    !repositoryPattern.test(repo) ||
    repo === "." ||
    repo === ".." ||
    !issueNumberPattern.test(issueNumberText)
  ) {
    throw new InvalidIssueUrlError("The GitHub owner, repository, or issue number is invalid.");
  }

  const issueNumber = Number(issueNumberText);

  if (!Number.isSafeInteger(issueNumber)) {
    throw new InvalidIssueUrlError("The GitHub issue number is outside the supported range.");
  }

  return {
    owner,
    repo,
    issueNumber,
    canonicalUrl: `https://github.com/${owner}/${repo}/issues/${issueNumber}`,
  };
}
