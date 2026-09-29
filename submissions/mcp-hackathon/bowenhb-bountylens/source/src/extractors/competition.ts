import type { NormalizedIssueContext } from "../github/normalize.js";
import { clampConfidence, type EvidenceSignal } from "./types.js";

export type CompetitionEvidence = {
  assigneeCount: number;
  claimCommentCount: number;
  pullRequestSignalCount: number;
  competitorCount: number;
};

const claimPattern = /(?:\/attempt|\/claim|\bclaim(?:ing)?\b|\bassign(?:ed)?\s+(?:this|me)|\bworking on (?:this|it)|\bI(?:'d| would)? like to (?:take|work on)|\bI can (?:take|implement)|认领|我来做|分配给我)/i;
const pullRequestPattern = /(?:github\.com\/[^\s]+\/pull\/\d+|\bPR\s*#?\d+|\bpull request\b|submitted (?:a )?PR)/i;

/** Extract observable competition signals; scoring is intentionally separate. */
export function extractCompetition(
  context: Pick<NormalizedIssueContext, "comments" | "issue">,
): EvidenceSignal<CompetitionEvidence> {
  const claimComments = context.comments.filter((comment) => claimPattern.test(comment.body));
  const pullRequestComments = context.comments.filter((comment) =>
    pullRequestPattern.test(comment.body),
  );
  const competitorAuthors = new Set([
    ...context.issue.assignees,
    ...claimComments.map((comment) => comment.author),
    ...pullRequestComments.map((comment) => comment.author),
  ]);

  const value = {
    assigneeCount: context.issue.assignees.length,
    claimCommentCount: claimComments.length,
    pullRequestSignalCount: pullRequestComments.length,
    competitorCount: competitorAuthors.size,
  };

  return {
    value,
    confidence: clampConfidence(context.comments.length === 0 ? 0.65 : 0.9),
    evidence: [
      `${value.assigneeCount} assignee(s) are present.`,
      `${value.claimCommentCount} claim comment(s) and ${value.pullRequestSignalCount} pull-request signal(s) were found.`,
      `${value.competitorCount} distinct competitor account role(s) were observed.`,
    ],
  };
}
