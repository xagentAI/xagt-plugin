import type { ActivityEvidence } from "../extractors/activity.js";
import type { CompetitionEvidence } from "../extractors/competition.js";
import type { RewardEvidence } from "../extractors/reward.js";
import type { ScopeEvidence } from "../extractors/scope.js";
import type { EvidenceSignal } from "../extractors/types.js";

export type Decision = "pursue" | "investigate" | "skip";

export type DeveloperProfile = {
  languages?: string[];
  hourlyRateUsd?: number;
  maxHours?: number;
};

export type DimensionScore = {
  score: number;
  confidence: number;
  evidence: string[];
};

export type DimensionName =
  | "scope_clarity"
  | "reward_evidence"
  | "repository_activity"
  | "maintainer_responsiveness"
  | "technical_fit"
  | "competition_pressure";

export type DimensionScores = Record<DimensionName, DimensionScore>;

export type ScoringInput = {
  scope: EvidenceSignal<ScopeEvidence>;
  reward: EvidenceSignal<RewardEvidence>;
  activity: EvidenceSignal<ActivityEvidence>;
  competition: EvidenceSignal<CompetitionEvidence>;
  repositoryLanguages: Record<string, number>;
  developerProfile?: DeveloperProfile;
};

export type EffortEstimate = {
  minHours: number;
  maxHours: number;
  confidence: number;
  evidence: string[];
};

export type OpportunityScore = {
  score: number;
  decision: Decision;
  confidence: number;
  dimensions: DimensionScores;
  estimatedEffort: EffortEstimate;
  evidence: string[];
  limitations: string[];
};
