import { describe, expect, it, vi } from "vitest";

import { loadFixture, type FixtureScenario } from "./fixture-loader.js";

const scenarios: FixtureScenario[] = [
  "clear-reward-low-competition",
  "clear-reward-high-competition",
  "no-explicit-reward",
];

function evidenceText(scenario: FixtureScenario): string {
  const { context } = loadFixture(scenario);
  return [context.issue.title, context.issue.body, ...context.comments.map(({ body }) => body)].join(
    "\n",
  );
}

describe("offline GitHub fixtures", () => {
  it("loads every scenario without making a network request", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    for (const scenario of scenarios) {
      const fixture = loadFixture(scenario);
      expect(fixture.scenario).toBe(scenario);
      expect(fixture.fixtureVersion).toBe(1);
      expect(fixture.sanitized).toBe(true);
      expect(fixture.context.issue.title.length).toBeGreaterThan(0);
      expect(fixture.context.repository.fullName).toContain("/");
    }

    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("contains distinct reward and competition signals", () => {
    const lowCompetition = loadFixture("clear-reward-low-competition");
    const highCompetition = loadFixture("clear-reward-high-competition");

    expect(evidenceText("clear-reward-low-competition")).toMatch(/(?:\$50|50 USD)/i);
    expect(evidenceText("clear-reward-high-competition")).toMatch(/(?:\$50|50 USD)/i);
    expect(evidenceText("no-explicit-reward")).not.toMatch(/bounty|reward|\$\d+|\d+ USD/i);
    expect(highCompetition.context.issue.assignees).toHaveLength(2);
    expect(highCompetition.context.comments.length).toBeGreaterThan(
      lowCompetition.context.comments.length,
    );
  });

  it("uses role aliases instead of personal account names", () => {
    const rolePattern = /^(?:automation|candidate-\d+|maintainer|reporter)$/;

    for (const scenario of scenarios) {
      const { context } = loadFixture(scenario);
      expect(context.issue.author).toMatch(rolePattern);
      expect(context.issue.assignees.every((author) => rolePattern.test(author))).toBe(true);
      expect(context.comments.every(({ author }) => rolePattern.test(author))).toBe(true);
    }
  });

  it("returns a fresh copy for each test consumer", () => {
    const first = loadFixture("no-explicit-reward");
    const originalTitle = first.context.issue.title;
    first.context.issue.title = "mutated in one test";

    expect(loadFixture("no-explicit-reward").context.issue.title).toBe(originalTitle);
  });
});
