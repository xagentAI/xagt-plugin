import { describe, expect, it } from "vitest";

import { extractActivity } from "../src/extractors/activity.js";
import { extractCompetition } from "../src/extractors/competition.js";
import { extractReward } from "../src/extractors/reward.js";
import { extractScope } from "../src/extractors/scope.js";
import type { NormalizedIssueContext } from "../src/github/normalize.js";
import { loadFixture } from "./fixture-loader.js";

function contextWithText(text: string): NormalizedIssueContext {
  const context = loadFixture("no-explicit-reward").context;
  context.issue.title = "Example task";
  context.issue.body = text;
  context.issue.labels = [];
  context.issue.assignees = [];
  context.comments = [];
  return context;
}

describe("extractReward", () => {
  it.each([
    ["Bounty: $100", 100],
    ["Reward is 100 USD after merge", 100],
    ["/bounty $1,250.50", 1_250.5],
    ["奖金 reward：50 USD", 50],
  ])("extracts an explicit amount from %s", (text, amount) => {
    expect(extractReward(contextWithText(text)).value).toMatchObject({
      amount,
      currency: "USD",
    });
  });

  it("finds the expected reward differences in offline fixtures", () => {
    expect(extractReward(loadFixture("clear-reward-low-competition").context).value.amount).toBe(
      50,
    );
    expect(extractReward(loadFixture("clear-reward-high-competition").context).value.amount).toBe(
      50,
    );
    expect(extractReward(loadFixture("no-explicit-reward").context).value.amount).toBeNull();
  });

  it.each([
    "The request budget is 100 calls per second.",
    "Use Node.js 20 and target 100% test coverage.",
    "The repository has 50 open issues.",
    "Payment handling is out of scope and no amount is offered.",
  ])("does not invent a reward from unrelated numbers: %s", (text) => {
    expect(extractReward(contextWithText(text)).value.amount).toBeNull();
  });

  it("handles a long body without unbounded scanning", () => {
    const context = contextWithText(`/bounty $125\n${"scope detail ".repeat(20_000)}`);
    const result = extractReward(context);
    expect(result.value.amount).toBe(125);
    expect(result.confidence).toBeGreaterThan(0.9);
  });
});

describe("extractScope", () => {
  it("extracts acceptance, reproduction, test, file, and action signals", () => {
    const result = extractScope(loadFixture("clear-reward-high-competition").context);
    expect(result.value.hasAcceptanceSection).toBe(true);
    expect(result.value.checklistItemCount).toBeGreaterThanOrEqual(5);
    expect(result.value.testSignalCount).toBeGreaterThan(0);
    expect(result.value.actionItemCount).toBeGreaterThan(0);
    expect(result.evidence.length).toBeGreaterThan(1);
  });

  it("supports multilingual headings and actions", () => {
    const context = contextWithText(
      "## 验收标准\n- [ ] 添加测试\n- [ ] 更新 `src/api.ts`\n## 复现步骤\n1. 运行 npm test",
    );
    const result = extractScope(context);
    expect(result.value).toMatchObject({
      hasAcceptanceSection: true,
      hasReproductionSection: true,
      checklistItemCount: 2,
      orderedStepCount: 1,
    });
    expect(result.value.fileReferenceCount).toBe(1);
  });

  it("returns low-confidence zero signals for an empty body", () => {
    const result = extractScope(contextWithText(""));
    expect(result.value.checklistItemCount).toBe(0);
    expect(result.value.testSignalCount).toBe(0);
    expect(result.confidence).toBeLessThan(0.5);
  });

  it("caps analysis of exceptionally long issue bodies", () => {
    const result = extractScope(contextWithText("x".repeat(150_000)));
    expect(result.value.analyzedCharacters).toBe(100_000);
    expect(result.value.wasTruncated).toBe(true);
  });
});

describe("extractCompetition", () => {
  it("separates high-competition and low-competition fixtures", () => {
    const high = extractCompetition(loadFixture("clear-reward-high-competition").context);
    const low = extractCompetition(loadFixture("clear-reward-low-competition").context);

    expect(high.value.assigneeCount).toBe(2);
    expect(high.value.claimCommentCount).toBeGreaterThanOrEqual(6);
    expect(high.value.competitorCount).toBeGreaterThan(low.value.competitorCount);
    expect(low.value.assigneeCount).toBe(0);
  });

  it("detects pull-request references separately from claims", () => {
    const context = contextWithText("Task body");
    context.comments = [
      {
        author: "candidate-1",
        body: "Submitted PR #42 for review.",
        createdAt: "2026-09-16T00:00:00Z",
      },
    ];
    expect(extractCompetition(context).value).toMatchObject({
      claimCommentCount: 0,
      pullRequestSignalCount: 1,
      competitorCount: 1,
    });
  });
});

describe("extractActivity", () => {
  it("extracts deterministic repository and issue ages", () => {
    const result = extractActivity(
      loadFixture("no-explicit-reward").context,
      "2026-09-17T00:00:00Z",
    );
    expect(result.value.daysSinceRepositoryPush).toBe(0);
    expect(result.value.daysSinceIssueUpdate).toBe(1);
    expect(result.evidence).toContain("0 maintainer response(s) found.");
  });

  it("calculates maintainer response time from public timestamps", () => {
    const context = contextWithText("Task body");
    context.issue.createdAt = "2026-09-15T08:00:00Z";
    context.comments = [
      {
        author: "maintainer",
        body: "Thanks, this is ready to implement.",
        createdAt: "2026-09-15T14:00:00Z",
        authorAssociation: "MEMBER",
      },
    ];
    const result = extractActivity(context, "2026-09-17T00:00:00Z");
    expect(result.value.maintainerResponseCount).toBe(1);
    expect(result.value.firstMaintainerResponseHours).toBe(6);
  });

  it("rejects an invalid reference time", () => {
    expect(() => extractActivity(contextWithText("Task body"), "not-a-date")).toThrow(RangeError);
  });
});

describe("extractor output contract", () => {
  it("returns value, confidence, and evidence without prohibited risk fields", () => {
    const context = loadFixture("clear-reward-low-competition").context;
    const outputs = [
      extractReward(context),
      extractScope(context),
      extractCompetition(context),
      extractActivity(context, "2026-09-17T00:00:00Z"),
    ];

    for (const output of outputs) {
      expect(Object.keys(output).sort()).toEqual(["confidence", "evidence", "value"]);
      expect(output.confidence).toBeGreaterThanOrEqual(0);
      expect(output.confidence).toBeLessThanOrEqual(1);
      expect(output.evidence.length).toBeGreaterThan(0);
      expect(JSON.stringify(output)).not.toMatch(/scam|fraud|paymentRisk|walletRisk|securityRisk/i);
    }
  });
});
