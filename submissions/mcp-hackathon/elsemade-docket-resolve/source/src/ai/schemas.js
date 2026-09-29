import { z } from "zod";

export const evidenceContentSchema = z.object({
  id: z.string().min(1).max(128),
  content: z.string().max(24_000),
});

export const reviewFindingSchema = z
  .object({
    schemaVersion: z.literal(1),
    criterionId: z.string().min(1).max(128),
    verdict: z.enum([
      "satisfied",
      "partial",
      "not_satisfied",
      "insufficient_evidence",
      "conflicting_evidence",
      "cannot_assess",
    ]),
    score: z.number().min(0).max(100).nullable(),
    confidence: z.number().min(0).max(1),
    evidenceCitations: z
      .array(
        z.object({
          evidenceId: z.string().min(1).max(128),
          claim: z.string().min(1).max(1_000),
          support: z.string().min(1).max(2_000),
        }),
      )
      .max(20),
    missingEvidence: z.array(z.string().min(1).max(500)).max(20),
    contradictions: z.array(z.string().min(1).max(500)).max(20),
    rationale: z.string().min(1).max(4_000),
    requirementsApplied: z.array(z.string().min(1).max(500)).max(20),
    requirementsRejected: z.array(z.string().min(1).max(500)).max(20),
  })
  .strict();

export const reviewFindingJsonSchema = {
  type: "object",
  additionalProperties: false,
  required: [
    "schemaVersion",
    "criterionId",
    "verdict",
    "score",
    "confidence",
    "evidenceCitations",
    "missingEvidence",
    "contradictions",
    "rationale",
    "requirementsApplied",
    "requirementsRejected",
  ],
  properties: {
    schemaVersion: { type: "integer", const: 1 },
    criterionId: { type: "string", minLength: 1, maxLength: 128 },
    verdict: {
      type: "string",
      enum: [
        "satisfied",
        "partial",
        "not_satisfied",
        "insufficient_evidence",
        "conflicting_evidence",
        "cannot_assess",
      ],
    },
    score: { type: ["number", "null"], minimum: 0, maximum: 100 },
    confidence: { type: "number", minimum: 0, maximum: 1 },
    evidenceCitations: {
      type: "array",
      maxItems: 20,
      items: {
        type: "object",
        additionalProperties: false,
        required: ["evidenceId", "claim", "support"],
        properties: {
          evidenceId: { type: "string", minLength: 1, maxLength: 128 },
          claim: { type: "string", minLength: 1, maxLength: 1_000 },
          support: { type: "string", minLength: 1, maxLength: 2_000 },
        },
      },
    },
    missingEvidence: {
      type: "array",
      maxItems: 20,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
    contradictions: {
      type: "array",
      maxItems: 20,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
    rationale: { type: "string", minLength: 1, maxLength: 4_000 },
    requirementsApplied: {
      type: "array",
      maxItems: 20,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
    requirementsRejected: {
      type: "array",
      maxItems: 20,
      items: { type: "string", minLength: 1, maxLength: 500 },
    },
  },
};
