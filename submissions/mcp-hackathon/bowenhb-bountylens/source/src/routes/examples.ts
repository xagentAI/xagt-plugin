import type { FastifyInstance } from "fastify";

import { createErrorResponse } from "../schemas/error.js";
import {
  evaluateResponseSchema,
  type EvaluateResponse,
} from "../schemas/response.js";

export const exampleIds = [
  "clear-reward-low-competition",
  "clear-reward-high-competition",
  "no-explicit-reward",
] as const;

export type ExampleId = (typeof exampleIds)[number];

type ExampleResponse = Omit<EvaluateResponse, "request_id">;

const sharedLimitations = [
  "The target repository source code was not executed.",
  "Effort is a coarse estimate derived from public issue metadata, not a delivery commitment.",
];

const examples: Record<ExampleId, ExampleResponse> = {
  "clear-reward-low-competition": {
    issue: {
      url: "https://github.com/QubesOS/qubes-issues/issues/9562",
      repository: "QubesOS/qubes-issues",
      number: 9562,
      state: "open",
    },
    decision: "investigate",
    score: 61,
    confidence: 0.7,
    estimated_effort: { min_hours: 2, max_hours: 5, confidence: 0.72 },
    reward: {
      amount: 50,
      currency: "USD",
      evidence: ["Explicit 50 USD reward found in a public issue comment."],
    },
    dimensions: {
      scope_clarity: 40,
      reward_evidence: 80,
      repository_activity: 88,
      maintainer_responsiveness: 30,
      technical_fit: 50,
      competition_pressure: 100,
    },
    evidence: [
      "The issue contains reproducible steps and file references.",
      "No assignee or implementation claim was observed.",
    ],
    next_actions: [
      "Confirm the acceptance and payment terms with the reward sponsor.",
      "Post an implementation claim before starting substantial work.",
    ],
    limitations: [...sharedLimitations, "Repository language data was unavailable or empty."],
  },
  "clear-reward-high-competition": {
    issue: {
      url: "https://github.com/copperheadhq/copperhead/issues/66",
      repository: "copperheadhq/copperhead",
      number: 66,
      state: "open",
    },
    decision: "investigate",
    score: 75,
    confidence: 0.87,
    estimated_effort: { min_hours: 7, max_hours: 13.5, confidence: 0.95 },
    reward: {
      amount: 50,
      currency: "USD",
      evidence: ["Explicit 50 USD reward found in the public issue body."],
    },
    dimensions: {
      scope_clarity: 83,
      reward_evidence: 97,
      repository_activity: 100,
      maintainer_responsiveness: 30,
      technical_fit: 99,
      competition_pressure: 0,
    },
    evidence: [
      "The issue contains explicit acceptance criteria and test requirements.",
      "Multiple assignees, claims, and pull-request signals create high competition.",
    ],
    next_actions: [
      "Review existing assignees, claims, and pull requests before starting work.",
      "Confirm that the reward is still available for a new implementation.",
    ],
    limitations: sharedLimitations,
  },
  "no-explicit-reward": {
    issue: {
      url: "https://github.com/fastify/fastify/issues/7030",
      repository: "fastify/fastify",
      number: 7030,
      state: "open",
    },
    decision: "skip",
    score: 54,
    confidence: 0.79,
    estimated_effort: { min_hours: 1.5, max_hours: 4, confidence: 0.68 },
    reward: {
      amount: null,
      currency: null,
      evidence: ["No explicit USD bounty or reward amount was found."],
    },
    dimensions: {
      scope_clarity: 37,
      reward_evidence: 0,
      repository_activity: 100,
      maintainer_responsiveness: 30,
      technical_fit: 100,
      competition_pressure: 100,
    },
    evidence: [
      "The repository is active and the task includes reproduction details.",
      "No explicit reward amount was found in the available public data.",
    ],
    next_actions: [
      "Confirm whether an explicit reward is available before investing implementation time.",
      "Ask the maintainer to confirm acceptance criteria and the expected test command.",
    ],
    limitations: sharedLimitations,
  },
};

function isExampleId(value: string): value is ExampleId {
  return (exampleIds as readonly string[]).includes(value);
}

/** Serve deterministic, offline examples for reviewers and API consumers. */
export function registerExampleRoutes(app: FastifyInstance): void {
  app.get<{ Params: { exampleId: string } }>(
    "/v1/examples/:exampleId",
    async (request, reply) => {
      const { exampleId } = request.params;
      if (!isExampleId(exampleId)) {
        return reply
          .code(404)
          .send(
            createErrorResponse(
              request.id,
              "EXAMPLE_NOT_FOUND",
              "The requested example does not exist.",
              false,
            ),
          );
      }

      return reply.code(200).send(
        evaluateResponseSchema.parse({
          request_id: request.id,
          ...examples[exampleId],
        }),
      );
    },
  );
}
