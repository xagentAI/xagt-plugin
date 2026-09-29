import { z } from "zod";

const decisionSchema = z.enum(["pursue", "investigate", "skip"]);
const boundedScoreSchema = z.number().int().min(0).max(100);
const confidenceSchema = z.number().min(0).max(1);

export const evaluateResponseSchema = z
  .object({
    request_id: z.string().min(1).max(128),
    issue: z
      .object({
        url: z.string().url(),
        repository: z.string().min(1),
        number: z.number().int().positive(),
        state: z.enum(["open", "closed"]),
      })
      .strict(),
    decision: decisionSchema,
    score: boundedScoreSchema,
    confidence: confidenceSchema,
    estimated_effort: z
      .object({
        min_hours: z.number().nonnegative(),
        max_hours: z.number().nonnegative(),
        confidence: confidenceSchema,
      })
      .strict(),
    reward: z
      .object({
        amount: z.number().positive().nullable(),
        currency: z.literal("USD").nullable(),
        evidence: z.array(z.string()).max(5),
      })
      .strict(),
    dimensions: z
      .object({
        scope_clarity: boundedScoreSchema,
        reward_evidence: boundedScoreSchema,
        repository_activity: boundedScoreSchema,
        maintainer_responsiveness: boundedScoreSchema,
        technical_fit: boundedScoreSchema,
        competition_pressure: boundedScoreSchema,
      })
      .strict(),
    evidence: z.array(z.string()).max(40),
    next_actions: z.array(z.string()).min(1).max(5),
    limitations: z.array(z.string()).min(1).max(10),
  })
  .strict();

export type EvaluateResponse = z.infer<typeof evaluateResponseSchema>;
