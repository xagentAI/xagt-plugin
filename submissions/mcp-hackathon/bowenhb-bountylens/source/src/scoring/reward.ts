import type { RewardEvidence } from "../extractors/reward.js";
import type { EvidenceSignal } from "../extractors/types.js";
import type { DimensionScore } from "./types.js";
import { clampScore, normalizeConfidence } from "./utils.js";

const sourceScores = {
  title: 95,
  body: 95,
  label: 85,
  comment: 78,
} as const;

/** Score evidence quality, not reward size or likelihood of payment. */
export function scoreRewardEvidence(reward: EvidenceSignal<RewardEvidence>): DimensionScore {
  const source = reward.value.source;
  if (reward.value.amount === null || source === null) {
    return {
      score: 0,
      confidence: normalizeConfidence(reward.confidence),
      evidence: ["No explicit USD reward amount is available to score."],
    };
  }

  const corroborationBonus = Math.min(Math.max(reward.value.sourceCount - 1, 0) * 2, 5);
  return {
    score: clampScore(sourceScores[source] + corroborationBonus),
    confidence: normalizeConfidence(reward.confidence),
    evidence: [
      `Explicit ${reward.value.amount} USD reward found in ${source}.`,
      `${reward.value.sourceCount} explicit reward signal(s) contributed ${corroborationBonus} corroboration point(s).`,
    ],
  };
}
