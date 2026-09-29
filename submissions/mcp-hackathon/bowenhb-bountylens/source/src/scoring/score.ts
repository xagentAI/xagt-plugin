import { scoreMaintainerResponsiveness, scoreRepositoryActivity } from "./activity.js";
import { scoreCompetitionPressure } from "./competition.js";
import { decisionThresholds, scoringWeights, totalScoringWeight } from "./config.js";
import { estimateEffort } from "./effort.js";
import { scoreRewardEvidence } from "./reward.js";
import { scoreScopeClarity } from "./scope.js";
import { scoreTechnicalFit } from "./technical-fit.js";
import type {
  Decision,
  DimensionScores,
  OpportunityScore,
  ScoringInput,
} from "./types.js";
import { clampScore, normalizeConfidence } from "./utils.js";

export function classifyScore(score: number): Decision {
  const normalized = clampScore(score);
  if (normalized >= decisionThresholds.pursue) return "pursue";
  if (normalized >= decisionThresholds.investigate) return "investigate";
  return "skip";
}

/** Calculate the configured weighted score from six already-bounded dimensions. */
export function calculateWeightedScore(dimensions: DimensionScores): number {
  const weightedTotal = Object.entries(scoringWeights).reduce(
    (total, [name, weight]) => total + dimensions[name as keyof DimensionScores].score * weight,
    0,
  );
  return clampScore(weightedTotal / totalScoringWeight);
}

function calculateOverallConfidence(dimensions: DimensionScores): number {
  const weightedTotal = Object.entries(scoringWeights).reduce(
    (total, [name, weight]) =>
      total + dimensions[name as keyof DimensionScores].confidence * weight,
    0,
  );
  return normalizeConfidence(weightedTotal / totalScoringWeight);
}

/** Run all deterministic dimension scorers and assemble an explainable opportunity score. */
export function scoreOpportunity(input: ScoringInput): OpportunityScore {
  const dimensions: DimensionScores = {
    scope_clarity: scoreScopeClarity(input.scope),
    reward_evidence: scoreRewardEvidence(input.reward),
    repository_activity: scoreRepositoryActivity(input.activity),
    maintainer_responsiveness: scoreMaintainerResponsiveness(input.activity),
    technical_fit: scoreTechnicalFit(input.repositoryLanguages, input.developerProfile),
    competition_pressure: scoreCompetitionPressure(input.competition),
  };
  const score = calculateWeightedScore(dimensions);
  const profileLanguages = input.developerProfile?.languages?.filter(
    (language) => language.trim().length > 0,
  );
  const limitations = [
    "The target repository source code was not executed.",
    "Effort is a coarse estimate derived from public issue metadata, not a delivery commitment.",
  ];
  if (profileLanguages === undefined || profileLanguages.length === 0) {
    limitations.push(
      "Developer languages were not supplied; technical fit uses a neutral score with lower confidence.",
    );
  }
  if (Object.values(input.repositoryLanguages).every((bytes) => bytes <= 0)) {
    limitations.push("Repository language data was unavailable or empty.");
  }

  return {
    score,
    decision: classifyScore(score),
    confidence: calculateOverallConfidence(dimensions),
    dimensions,
    estimatedEffort: estimateEffort(input.scope),
    evidence: Object.entries(dimensions).flatMap(([name, dimension]) =>
      dimension.evidence.map((item) => `${name}: ${item}`),
    ),
    limitations,
  };
}
