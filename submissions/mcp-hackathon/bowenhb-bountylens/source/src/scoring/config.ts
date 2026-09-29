import type { DimensionName } from "./types.js";

/** Central scoring configuration. Dimension functions contain no hidden weights. */
export const scoringWeights = {
  scope_clarity: 25,
  reward_evidence: 20,
  repository_activity: 15,
  maintainer_responsiveness: 15,
  technical_fit: 15,
  competition_pressure: 10,
} as const satisfies Record<DimensionName, number>;

export const decisionThresholds = {
  pursue: 80,
  investigate: 60,
} as const;

export const totalScoringWeight = Object.values(scoringWeights).reduce(
  (total, weight) => total + weight,
  0,
);

if (totalScoringWeight !== 100) {
  throw new Error(`Scoring weights must total 100; received ${totalScoringWeight}.`);
}
