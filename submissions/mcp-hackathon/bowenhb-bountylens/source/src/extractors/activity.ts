import type { NormalizedIssueContext } from "../github/normalize.js";
import { clampConfidence, type EvidenceSignal } from "./types.js";

export type ActivityEvidence = {
  daysSinceRepositoryUpdate: number | null;
  daysSinceRepositoryPush: number | null;
  daysSinceIssueUpdate: number | null;
  maintainerResponseCount: number;
  firstMaintainerResponseHours: number | null;
};

const millisecondsPerDay = 86_400_000;
const maintainerAssociations = new Set(["OWNER", "MEMBER", "COLLABORATOR"]);

function parseTimestamp(value: string | null): number | null {
  if (value === null) return null;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) ? timestamp : null;
}

function elapsedDays(referenceTime: number, value: string | null): number | null {
  const timestamp = parseTimestamp(value);
  return timestamp === null ? null : Math.max(0, Math.floor((referenceTime - timestamp) / millisecondsPerDay));
}

/** Extract repository freshness and maintainer-response timing at a supplied reference time. */
export function extractActivity(
  context: NormalizedIssueContext,
  referenceTime: string | number | Date,
): EvidenceSignal<ActivityEvidence> {
  const referenceTimestamp = new Date(referenceTime).getTime();
  if (!Number.isFinite(referenceTimestamp)) {
    throw new RangeError("Activity reference time must be a valid date or timestamp.");
  }

  const maintainerComments = context.comments.filter(
    (comment) =>
      comment.authorAssociation !== undefined &&
      maintainerAssociations.has(comment.authorAssociation.toUpperCase()),
  );
  const issueCreatedAt = parseTimestamp(context.issue.createdAt);
  const firstMaintainerCommentAt = parseTimestamp(maintainerComments[0]?.createdAt ?? null);
  const firstMaintainerResponseHours =
    issueCreatedAt === null || firstMaintainerCommentAt === null
      ? null
      : Math.max(0, (firstMaintainerCommentAt - issueCreatedAt) / 3_600_000);

  const value = {
    daysSinceRepositoryUpdate: elapsedDays(referenceTimestamp, context.repository.updatedAt),
    daysSinceRepositoryPush: elapsedDays(referenceTimestamp, context.repository.pushedAt),
    daysSinceIssueUpdate: elapsedDays(referenceTimestamp, context.issue.updatedAt),
    maintainerResponseCount: maintainerComments.length,
    firstMaintainerResponseHours,
  };

  const evidence = [
    `Repository update age: ${value.daysSinceRepositoryUpdate ?? "unknown"} day(s).`,
    `Repository push age: ${value.daysSinceRepositoryPush ?? "unknown"} day(s).`,
    `Issue update age: ${value.daysSinceIssueUpdate ?? "unknown"} day(s).`,
    `${value.maintainerResponseCount} maintainer response(s) found.`,
  ];
  if (firstMaintainerResponseHours !== null) {
    evidence.push(`First maintainer response arrived after ${firstMaintainerResponseHours.toFixed(1)} hour(s).`);
  }

  const knownTimestamps = [
    value.daysSinceRepositoryUpdate,
    value.daysSinceRepositoryPush,
    value.daysSinceIssueUpdate,
  ].filter((value) => value !== null).length;

  return {
    value,
    confidence: clampConfidence(0.45 + knownTimestamps * 0.12 + (maintainerComments.length > 0 ? 0.12 : 0)),
    evidence,
  };
}
