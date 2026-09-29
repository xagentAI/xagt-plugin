import type { CompetitionEvidence } from "../extractors/competition.js";
import type { EvidenceSignal } from "../extractors/types.js";
import type { DimensionScore } from "./types.js";
import { clampScore, normalizeConfidence } from "./utils.js";

/** Return an opportunity-friendly score: low observed competition produces a high score. */
export function scoreCompetitionPressure(
  competition: EvidenceSignal<CompetitionEvidence>,
): DimensionScore {
  const value = competition.value;
  const penalties = {
    assignees: Math.min(value.assigneeCount * 25, 50),
    claims: Math.min(value.claimCommentCount * 8, 40),
    pullRequests: Math.min(value.pullRequestSignalCount * 20, 40),
    competitors: Math.min(value.competitorCount * 7, 35),
  };
  const totalPenalty = Object.values(penalties).reduce((total, penalty) => total + penalty, 0);

  return {
    score: clampScore(100 - totalPenalty),
    confidence: normalizeConfidence(competition.confidence),
    evidence: [
      `${value.assigneeCount} assignee(s): -${penalties.assignees} point(s).`,
      `${value.claimCommentCount} claim(s): -${penalties.claims} point(s).`,
      `${value.pullRequestSignalCount} pull-request signal(s): -${penalties.pullRequests} point(s).`,
      `${value.competitorCount} distinct competitor(s): -${penalties.competitors} point(s).`,
    ],
  };
}
