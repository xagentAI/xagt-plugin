import type { NormalizedIssueContext } from "../src/github/normalize.js";

import highCompetitionJson from "./fixtures/clear-reward-high-competition.json";
import lowCompetitionJson from "./fixtures/clear-reward-low-competition.json";
import noRewardJson from "./fixtures/no-explicit-reward.json";

export type FixtureScenario =
  | "clear-reward-high-competition"
  | "clear-reward-low-competition"
  | "no-explicit-reward";

export type OfflineFixture = {
  fixtureVersion: number;
  sanitized: boolean;
  scenario: FixtureScenario;
  sourceUrl: string;
  capturedAt: string;
  context: NormalizedIssueContext;
};

// Static JSON imports make the default test suite deterministic and network-free.
const fixtures = {
  "clear-reward-high-competition": highCompetitionJson,
  "clear-reward-low-competition": lowCompetitionJson,
  "no-explicit-reward": noRewardJson,
} as unknown as Readonly<Record<FixtureScenario, OfflineFixture>>;

/** Return an isolated copy so one test cannot mutate another test's fixture. */
export function loadFixture(scenario: FixtureScenario): OfflineFixture {
  return structuredClone(fixtures[scenario]);
}
