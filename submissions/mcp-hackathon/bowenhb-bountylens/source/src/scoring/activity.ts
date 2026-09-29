import type { ActivityEvidence } from "../extractors/activity.js";
import type { EvidenceSignal } from "../extractors/types.js";
import type { DimensionScore } from "./types.js";
import { average, clampScore, normalizeConfidence } from "./utils.js";

function freshnessScore(days: number): number {
  if (days <= 7) return 100;
  if (days <= 30) return 85;
  if (days <= 90) return 65;
  if (days <= 180) return 45;
  if (days <= 365) return 25;
  return 10;
}

/** Score public repository and issue freshness while treating unknown dates as neutral. */
export function scoreRepositoryActivity(
  activity: EvidenceSignal<ActivityEvidence>,
): DimensionScore {
  const ages = [
    activity.value.daysSinceRepositoryUpdate,
    activity.value.daysSinceRepositoryPush,
    activity.value.daysSinceIssueUpdate,
  ];
  const knownAges = ages.filter((age): age is number => age !== null && Number.isFinite(age));

  if (knownAges.length === 0) {
    return {
      score: 50,
      confidence: 0.2,
      evidence: ["Repository and issue activity dates are unavailable; a neutral score was used."],
    };
  }

  return {
    score: clampScore(average(knownAges.map(freshnessScore))),
    confidence: normalizeConfidence(activity.confidence * (knownAges.length / ages.length)),
    evidence: knownAges.map(
      (days) => `${days} day(s) since an observed activity event maps to ${freshnessScore(days)} point(s).`,
    ),
  };
}

/** Score observable maintainer replies and their first-response delay. */
export function scoreMaintainerResponsiveness(
  activity: EvidenceSignal<ActivityEvidence>,
): DimensionScore {
  const { firstMaintainerResponseHours, maintainerResponseCount } = activity.value;
  if (maintainerResponseCount === 0) {
    return {
      score: 30,
      confidence: normalizeConfidence(activity.confidence * 0.8),
      evidence: ["No maintainer response was observed in the available issue comments."],
    };
  }

  let timingScore = 55;
  if (firstMaintainerResponseHours !== null) {
    if (firstMaintainerResponseHours <= 24) timingScore = 100;
    else if (firstMaintainerResponseHours <= 72) timingScore = 85;
    else if (firstMaintainerResponseHours <= 168) timingScore = 70;
    else if (firstMaintainerResponseHours <= 720) timingScore = 50;
    else timingScore = 35;
  }
  const responseBonus = Math.min(maintainerResponseCount - 1, 3) * 3;

  return {
    score: clampScore(timingScore + responseBonus),
    confidence: normalizeConfidence(
      activity.confidence * (firstMaintainerResponseHours === null ? 0.75 : 1),
    ),
    evidence: [
      `${maintainerResponseCount} maintainer response(s) were observed.`,
      firstMaintainerResponseHours === null
        ? "First-response timing is unavailable."
        : `First maintainer response arrived after ${firstMaintainerResponseHours.toFixed(1)} hour(s).`,
    ],
  };
}
