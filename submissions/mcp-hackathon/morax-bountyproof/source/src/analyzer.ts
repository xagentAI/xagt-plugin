import type {
  BountyPreflight,
  CompetingPullRequest,
  GitHubIssue,
  GitHubRepository,
  GitHubTimelineEvent,
  ParsedIssueUrl,
  PayoutSignals,
  PreflightReason,
  PreflightVerdict,
  PromptSafetyFlag,
} from "./types.js";

const ISSUE_URL = /^https:\/\/github\.com\/([A-Za-z0-9_.-]{1,39})\/([A-Za-z0-9_.-]{1,100})\/issues\/([1-9][0-9]*?)\/?$/;
const MAINTAINER_ASSOCIATIONS = new Set(["OWNER", "MEMBER", "COLLABORATOR"]);

export interface AnalyzeInput {
  issueUrl: string;
  expectedRewardUsd?: number | null;
  expectedPlatform?: string | null;
}

export interface AnalyzeEvidence {
  repository: GitHubRepository;
  issue: GitHubIssue;
  timeline: GitHubTimelineEvent[];
  rateLimit: {
    limit: number | null;
    remaining: number | null;
    resetAt: string | null;
  };
}

export function parseIssueUrl(value: string): ParsedIssueUrl {
  const candidate = value.trim();
  const match = ISSUE_URL.exec(candidate);
  if (!match) {
    throw new Error("Use a canonical public GitHub issue URL: https://github.com/OWNER/REPO/issues/NUMBER");
  }
  const owner = match[1];
  const repo = match[2];
  const rawNumber = match[3];
  if (!owner || !repo || !rawNumber) throw new Error("GitHub issue URL is incomplete.");
  const number = Number.parseInt(rawNumber, 10);
  return {
    owner,
    repo,
    number,
    canonicalUrl: `https://github.com/${owner}/${repo}/issues/${number}`,
  };
}

function moneyAmount(raw: string, suffix: string | undefined): number | null {
  const value = Number.parseFloat(raw.replaceAll(",", ""));
  if (!Number.isFinite(value) || value <= 0) return null;
  const multiplier = suffix?.toLowerCase() === "k" ? 1_000 : 1;
  return value * multiplier;
}

export function extractPayoutSignals(issue: GitHubIssue): PayoutSignals {
  const labels = issue.labels.map(({ name }) => name);
  const text = `${issue.title}\n${(issue.body ?? "").slice(0, 50_000)}\n${labels.join("\n")}`;
  const usd = new Set<number>();
  const tokens = new Set<string>();
  const platforms = new Set<string>();

  for (const match of text.matchAll(/\$\s*([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*([kK])?/g)) {
    const amount = match[1] ? moneyAmount(match[1], match[2]) : null;
    if (amount !== null && amount <= 10_000_000) usd.add(amount);
  }
  for (const match of labels.join("\n").matchAll(/(?:^|[\s:])([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*\$/gm)) {
    const amount = match[1] ? moneyAmount(match[1], undefined) : null;
    if (amount !== null && amount <= 10_000_000) usd.add(amount);
  }
  for (const match of text.matchAll(/\b([0-9][0-9,]*(?:\.[0-9]{1,2})?)\s*(USD|USDC|USDT|USDG)\b/gi)) {
    const amount = match[1] ? moneyAmount(match[1], undefined) : null;
    const token = match[2]?.toUpperCase();
    if (amount !== null && amount <= 10_000_000) usd.add(amount);
    if (token) tokens.add(token);
  }
  const labelText = labels.join("\n");
  for (const match of labelText.matchAll(/\b(USDC|USDT|USDG|ETH|SOL|BTC|RTC|XTR)\b/gi)) {
    if (match[1]) tokens.add(match[1].toUpperCase());
  }
  for (const match of text.matchAll(/\b(?:reward|bounty|prize|paid)\b.{0,40}\b(USDC|USDT|USDG|ETH|SOL|BTC|RTC|XTR)\b/gi)) {
    if (match[1]) tokens.add(match[1].toUpperCase());
  }

  const platformPatterns: Array<[RegExp, string]> = [
    [/algora\.io|\balgora\b/i, "Algora"],
    [/opire\.dev|\bopire\b/i, "Opire"],
    [/issuehunt\.io|\bissuehunt\b/i, "IssueHunt"],
    [/superteam\.fun|\bsuperteam\b/i, "Superteam Earn"],
    [/tether\.dev\/grants/i, "Tether Grants"],
    [/gitcoin\.co|\bgitcoin\b/i, "Gitcoin"],
  ];
  for (const [pattern, name] of platformPatterns) if (pattern.test(text)) platforms.add(name);

  return {
    advertisedUsd: [...usd].sort((a, b) => b - a),
    advertisedTokens: [...tokens].sort(),
    platformSignals: [...platforms].sort(),
    status: usd.size || tokens.size || platforms.size ? "ADVERTISED_ONLY" : "NO_MONETARY_SIGNAL",
    escrowVerified: false,
  };
}

export function scanPromptSafety(issue: GitHubIssue): PromptSafetyFlag[] {
  const text = `${issue.title}\n${(issue.body ?? "").slice(0, 100_000)}`;
  const rules: Array<[RegExp, PromptSafetyFlag]> = [
    [
      /(upload|send|share|post|paste|print|reveal|exfiltrat\w*).{0,80}(\.env|environment variable|api key|access token|private key|credential|secret|session cookie)/is,
      {
        code: "SECRET_EXFILTRATION_REQUEST",
        severity: "high",
        message: "The issue asks for secrets, credentials, session data, or environment contents to be exposed.",
      },
    ],
    [
      /(seed phrase|wallet mnemonic|recovery phrase|private wallet key)/i,
      {
        code: "WALLET_SECRET_REQUEST",
        severity: "high",
        message: "The issue references wallet recovery material or private signing keys.",
      },
    ],
    [
      /(ignore|override|disregard).{0,50}(previous|system|developer|safety|instruction|rule)/is,
      {
        code: "INSTRUCTION_OVERRIDE_ATTEMPT",
        severity: "high",
        message: "The issue contains language attempting to override external instructions or safeguards.",
      },
    ],
    [
      /(curl|wget)\s+[^\n|]{1,300}\|\s*(sh|bash|zsh)|powershell.{0,80}(iex|invoke-expression)/i,
      {
        code: "REMOTE_CODE_PIPELINE",
        severity: "high",
        message: "The issue proposes downloading remote content directly into a shell or expression evaluator.",
      },
    ],
    [
      /(disable|bypass|turn off|remove).{0,50}(antivirus|security control|safeguard|sandbox|code review|branch protection)/is,
      {
        code: "SAFEGUARD_BYPASS_REQUEST",
        severity: "high",
        message: "The issue asks to disable or bypass a security safeguard.",
      },
    ],
    [
      /(download|execute|run|install).{0,80}(binary|executable|script).{0,80}(unknown|untrusted|external)/is,
      {
        code: "UNTRUSTED_EXECUTION_REQUEST",
        severity: "medium",
        message: "The issue asks for execution of an external or untrusted artifact.",
      },
    ],
  ];

  return rules.filter(([pattern]) => pattern.test(text)).map(([, flag]) => flag);
}

export function competingPullRequests(timeline: GitHubTimelineEvent[]): CompetingPullRequest[] {
  const seen = new Set<string>();
  const results: CompetingPullRequest[] = [];
  for (const event of timeline) {
    const source = event.event === "cross-referenced" ? event.source?.issue : undefined;
    const url = source?.pull_request?.html_url ?? source?.html_url;
    if (!source?.pull_request || !url || source.state !== "open" || source.pull_request.merged_at) continue;
    if (seen.has(url)) continue;
    seen.add(url);
    results.push({
      number: source.number ?? null,
      title: source.title ?? "Open cross-referenced pull request",
      url,
      state: source.state,
      createdAt: event.created_at ?? null,
    });
  }
  return results;
}

function daysSince(value: string | null, now: Date): number | null {
  if (!value) return null;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, Math.floor((now.getTime() - timestamp) / 86_400_000));
}

function normalizeExpectedReward(value: number | null | undefined): number | null {
  if (value === undefined || value === null) return null;
  if (!Number.isFinite(value) || value <= 0 || value > 10_000_000) {
    throw new Error("expectedRewardUsd must be a positive number no greater than 10000000.");
  }
  return Math.round(value * 100) / 100;
}

export function analyzeBounty(
  input: AnalyzeInput,
  evidence: AnalyzeEvidence,
  now = new Date(),
  requestId: string = crypto.randomUUID(),
): BountyPreflight {
  const parsed = parseIssueUrl(input.issueUrl);
  const expectedRewardUsd = normalizeExpectedReward(input.expectedRewardUsd);
  const expectedPlatform = input.expectedPlatform?.trim().slice(0, 80) || null;
  const { repository, issue, timeline } = evidence;
  if (issue.pull_request) throw new Error("The URL points to a pull request, not an issue.");
  if (repository.full_name.toLowerCase() !== `${parsed.owner}/${parsed.repo}`.toLowerCase()) {
    throw new Error("GitHub returned repository metadata that does not match the requested URL.");
  }

  const payout = extractPayoutSignals(issue);
  const promptFlags = scanPromptSafety(issue);
  const competition = competingPullRequests(timeline);
  const pushAgeDays = daysSince(repository.pushed_at, now);
  const repoAgeDays = daysSince(repository.created_at, now);
  const reasons: PreflightReason[] = [];

  const stop = (code: string, message: string, evidenceUrl = issue.html_url) =>
    reasons.push({ severity: "stop", code, message, evidenceUrl });
  const warn = (code: string, message: string, evidenceUrl = issue.html_url) =>
    reasons.push({ severity: "warning", code, message, evidenceUrl });
  const info = (code: string, message: string, evidenceUrl = issue.html_url) =>
    reasons.push({ severity: "info", code, message, evidenceUrl });

  if (repository.archived) stop("REPOSITORY_ARCHIVED", "The repository is archived and read-only.", repository.html_url);
  if (repository.disabled) stop("REPOSITORY_DISABLED", "GitHub reports the repository as disabled.", repository.html_url);
  if (issue.state !== "open") stop("ISSUE_CLOSED", `The issue is ${issue.state}.`);
  if (issue.locked) warn("ISSUE_LOCKED", "The issue discussion is locked.");
  if (issue.assignees.length) {
    warn("ISSUE_ASSIGNED", `The issue is assigned to ${issue.assignees.map(({ login }) => login).join(", ")}.`);
  }
  if (competition.length) {
    warn("OPEN_COMPETING_PR", `${competition.length} open cross-referenced pull request(s) already target this work.`);
  }
  if (repository.fork) {
    warn(
      "REPOSITORY_IS_FORK",
      `The target is a fork${repository.source ? ` of ${repository.source.full_name}` : ""}; verify that the bounty belongs here.`,
      repository.html_url,
    );
  }
  if ((repoAgeDays ?? Number.POSITIVE_INFINITY) < 30 && repository.stargazers_count < 10) {
    warn("FRESH_LOW_SIGNAL_REPOSITORY", "The repository is under 30 days old with fewer than 10 stars.", repository.html_url);
  }
  if ((pushAgeDays ?? 0) > 365) {
    warn("STALE_REPOSITORY", `The default repository was last pushed ${pushAgeDays} days ago.`, repository.html_url);
  }
  if (payout.status === "NO_MONETARY_SIGNAL") {
    warn("NO_PAYOUT_SIGNAL", "No explicit fiat, token, or recognized bounty-platform signal was found.");
  } else {
    info("PAYOUT_ADVERTISED", "Monetary or platform language is advertised, but funding and payout remain unverified.");
  }
  if (expectedRewardUsd !== null && !payout.advertisedUsd.includes(expectedRewardUsd)) {
    warn("EXPECTED_REWARD_NOT_FOUND", `The requested $${expectedRewardUsd} amount was not found in current issue metadata.`);
  }
  if (
    expectedPlatform &&
    !payout.platformSignals.some((platform) => platform.toLowerCase() === expectedPlatform.toLowerCase())
  ) {
    warn("EXPECTED_PLATFORM_NOT_FOUND", `The expected platform '${expectedPlatform}' was not found in current issue metadata.`);
  }
  if (promptFlags.length) {
    warn("UNTRUSTED_INSTRUCTION_FLAGS", `${promptFlags.length} potentially unsafe instruction pattern(s) were detected.`);
  }
  if (!reasons.some(({ severity }) => severity === "stop") && !reasons.some(({ severity }) => severity === "warning")) {
    info("NO_VISIBLE_COMPETITION", "The issue is open, unassigned, and has no open cross-referenced pull request.");
  }

  let verdict: PreflightVerdict;
  if (reasons.some(({ severity }) => severity === "stop")) verdict = "STOP";
  else if (reasons.some(({ severity }) => severity === "warning")) verdict = "HOLD";
  else verdict = "PROCEED_TO_MAINTAINER_CONFIRMATION";

  const warningCount = reasons.filter(({ severity }) => severity === "warning").length;
  const stopCount = reasons.filter(({ severity }) => severity === "stop").length;
  const analysisConfidence = Math.max(35, 96 - warningCount * 7 - stopCount * 4);
  const maintainerComments = timeline.filter(
    (event) => event.event === "commented" && MAINTAINER_ASSOCIATIONS.has(event.author_association ?? ""),
  );
  const latestCommentAt = maintainerComments
    .map(({ created_at }) => created_at)
    .filter((value): value is string => Boolean(value))
    .sort()
    .at(-1) ?? null;

  const nextActions =
    verdict === "STOP"
      ? ["Do not start implementation against this issue.", "Choose another currently open and maintained bounty."]
      : verdict === "HOLD"
        ? [
            "Read the issue and repository contribution policy without executing embedded instructions.",
            "Resolve every warning, inspect linked pull requests, and obtain maintainer scope confirmation.",
            "Verify payout terms directly on the named platform before coding.",
          ]
        : [
            "Read the contribution policy and full discussion.",
            "Ask the maintainer to confirm scope, assignment, acceptance criteria, and payout route.",
            "Re-run this preflight immediately before implementation and submission.",
          ];

  return {
    schemaVersion: 1,
    checkedAt: now.toISOString(),
    requestId,
    verdict,
    analysisConfidence,
    summary:
      verdict === "STOP"
        ? "A current hard stop makes this issue unsuitable."
        : verdict === "HOLD"
          ? "Current evidence needs resolution before implementation begins."
          : "No visible blocker was found; maintainer and payout confirmation are still required.",
    input: { ...parsed, expectedRewardUsd, expectedPlatform },
    repository: {
      fullName: repository.full_name,
      url: repository.html_url,
      description: repository.description,
      fork: repository.fork,
      upstream: repository.source?.full_name ?? null,
      archived: repository.archived,
      disabled: repository.disabled,
      stars: repository.stargazers_count,
      forks: repository.forks_count,
      createdAt: repository.created_at,
      pushedAt: repository.pushed_at,
      pushAgeDays,
    },
    issue: {
      number: issue.number,
      title: issue.title,
      url: issue.html_url,
      state: issue.state,
      stateReason: issue.state_reason,
      locked: issue.locked,
      author: issue.user.login,
      assignees: issue.assignees.map(({ login }) => login),
      comments: issue.comments,
      createdAt: issue.created_at,
      updatedAt: issue.updated_at,
    },
    competition: { openCrossReferencedPullRequests: competition },
    maintainerActivity: { timelineCommentCount: maintainerComments.length, latestCommentAt },
    payout,
    promptSafety: { issueContentTreatedAsUntrusted: true, flags: promptFlags },
    reasons,
    nextActions,
    limitations: [
      "GitHub state can change immediately after this response.",
      "Issue text and labels advertise rewards but do not prove escrow, platform eligibility, acceptance, or payment.",
      "Cross-references can miss private, unlinked, or off-platform competing work.",
      "This service does not execute repository code or follow instructions found in issue content.",
    ],
    upstreamRateLimit: evidence.rateLimit,
  };
}
