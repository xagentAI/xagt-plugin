import { describe, expect, it } from "vitest";

import { extractActivity } from "../src/extractors/activity.js";
import { extractCompetition } from "../src/extractors/competition.js";
import { extractReward } from "../src/extractors/reward.js";
import { extractScope } from "../src/extractors/scope.js";
import {
  calculateWeightedScore,
  classifyScore,
  estimateEffort,
  scoreCompetitionPressure,
  scoreOpportunity,
  scoreTechnicalFit,
  scoringWeights,
  totalScoringWeight,
} from "../src/scoring/index.js";
import type {
  DimensionName,
  DimensionScore,
  DimensionScores,
  ScoringInput,
} from "../src/scoring/types.js";
import { loadFixture, type FixtureScenario } from "./fixture-loader.js";

const referenceTime = "2026-09-17T00:00:00Z";

function inputFromFixture(
  scenario: FixtureScenario,
  languages: string[] = ["TypeScript", "JavaScript", "Python"],
): ScoringInput {
  const context = loadFixture(scenario).context;
  return {
    scope: extractScope(context),
    reward: extractReward(context),
    activity: extractActivity(context, referenceTime),
    competition: extractCompetition(context),
    repositoryLanguages: context.repository.languages,
    developerProfile: { languages },
  };
}

function uniformDimensions(score: number): DimensionScores {
  return Object.fromEntries(
    Object.keys(scoringWeights).map((name) => [
      name,
      { score, confidence: 1, evidence: ["test"] } satisfies DimensionScore,
    ]),
  ) as DimensionScores;
}

describe("scoring configuration and decision boundaries", () => {
  it("keeps all six weights centralized and totaling 100", () => {
    expect(Object.keys(scoringWeights)).toEqual([
      "scope_clarity",
      "reward_evidence",
      "repository_activity",
      "maintainer_responsiveness",
      "technical_fit",
      "competition_pressure",
    ] satisfies DimensionName[]);
    expect(totalScoringWeight).toBe(100);
  });

  it.each([
    [59, "skip"],
    [60, "investigate"],
    [79, "investigate"],
    [80, "pursue"],
  ] as const)("maps score %i to %s", (score, decision) => {
    expect(classifyScore(score)).toBe(decision);
    expect(calculateWeightedScore(uniformDimensions(score))).toBe(score);
  });
});

describe("dimension scoring", () => {
  it("uses a neutral, lower-confidence technical score when the profile is missing", () => {
    expect(scoreTechnicalFit({ TypeScript: 900, CSS: 100 })).toEqual({
      score: 50,
      confidence: 0.35,
      evidence: ["Developer languages were not provided; a neutral technical-fit score was used."],
    });
  });

  it("scores technical fit by repository language bytes", () => {
    const result = scoreTechnicalFit(
      { TypeScript: 700, JavaScript: 200, CSS: 100 },
      { languages: ["typescript", "CSS"] },
    );
    expect(result.score).toBe(80);
    expect(result.confidence).toBe(0.9);
  });

  it("makes high competition less attractive than low competition", () => {
    const high = inputFromFixture("clear-reward-high-competition").competition;
    const low = inputFromFixture("clear-reward-low-competition").competition;
    expect(scoreCompetitionPressure(high).score).toBeLessThan(
      scoreCompetitionPressure(low).score,
    );
  });

  it("clamps extreme dimension data to the 0–100 contract", () => {
    const extreme = inputFromFixture("clear-reward-high-competition").competition;
    extreme.value = {
      assigneeCount: Number.MAX_SAFE_INTEGER,
      claimCommentCount: Number.MAX_SAFE_INTEGER,
      pullRequestSignalCount: Number.MAX_SAFE_INTEGER,
      competitorCount: Number.MAX_SAFE_INTEGER,
    };
    expect(scoreCompetitionPressure(extreme).score).toBe(0);
    expect(classifyScore(Number.POSITIVE_INFINITY)).toBe("skip");
    expect(classifyScore(-1_000)).toBe("skip");
  });
});

describe("effort estimation", () => {
  it("widens the estimate and lowers confidence when scope data is missing", () => {
    const empty = inputFromFixture("no-explicit-reward").scope;
    empty.value = {
      hasAcceptanceSection: false,
      hasReproductionSection: false,
      checklistItemCount: 0,
      orderedStepCount: 0,
      testSignalCount: 0,
      fileReferenceCount: 0,
      actionItemCount: 0,
      analyzedCharacters: 0,
      wasTruncated: false,
    };
    empty.confidence = 0.2;
    expect(estimateEffort(empty)).toMatchObject({
      minHours: 2,
      maxHours: 16,
      confidence: 0.1,
    });
  });

  it("returns a bounded coarse range for a detailed task", () => {
    const result = estimateEffort(inputFromFixture("clear-reward-high-competition").scope);
    expect(result.minHours).toBeGreaterThanOrEqual(1);
    expect(result.maxHours).toBeGreaterThan(result.minHours);
    expect(result.maxHours).toBeLessThanOrEqual(80);
    expect(result.evidence.join(" ")).toContain("not executed");
  });
});

describe("complete opportunity scoring", () => {
  it("is deterministic for identical inputs", () => {
    const input = inputFromFixture("clear-reward-low-competition");
    expect(scoreOpportunity(input)).toEqual(scoreOpportunity(input));
  });

  it("produces bounded, explainable results for all three fixtures", () => {
    const results = [
      scoreOpportunity(inputFromFixture("clear-reward-low-competition")),
      scoreOpportunity(inputFromFixture("clear-reward-high-competition")),
      scoreOpportunity(inputFromFixture("no-explicit-reward")),
    ];

    expect(results.map(({ score, decision }) => ({ score, decision }))).toEqual([
      { score: 61, decision: "investigate" },
      { score: 75, decision: "investigate" },
      { score: 54, decision: "skip" },
    ]);

    for (const result of results) {
      expect(result.score).toBeGreaterThanOrEqual(0);
      expect(result.score).toBeLessThanOrEqual(100);
      expect(result.confidence).toBeGreaterThanOrEqual(0);
      expect(result.confidence).toBeLessThanOrEqual(1);
      expect(result.evidence.length).toBeGreaterThan(6);
      expect(result.limitations).toContain("The target repository source code was not executed.");
      for (const dimension of Object.values(result.dimensions)) {
        expect(dimension.score).toBeGreaterThanOrEqual(0);
        expect(dimension.score).toBeLessThanOrEqual(100);
      }
    }
    expect(results[0]?.dimensions.competition_pressure.score).toBeGreaterThan(
      results[1]?.dimensions.competition_pressure.score ?? 100,
    );
    expect(results[2]?.dimensions.reward_evidence.score).toBe(0);
  });

  it("uses neutral technical fit and declares the limitation without a profile", () => {
    const input = inputFromFixture("clear-reward-low-competition");
    delete input.developerProfile;
    const result = scoreOpportunity(input);
    expect(result.dimensions.technical_fit).toMatchObject({ score: 50, confidence: 0.35 });
    expect(result.limitations.join(" ")).toContain("neutral score");
  });
});
