import { z } from "zod";

export const objectiveSchema = z.enum(["leads", "signups", "purchases", "revenue"]);
export const platformSchema = z.enum(["auto", "linkedin", "x", "reddit", "xiaohongshu", "wechat"]);
export const resolvedPlatformSchema = platformSchema.exclude(["auto"]);

export const createMissionSchema = z
  .object({
    sourceUrl: z.url({ protocol: /^https?$/ }).max(2_048),
    objective: objectiveSchema,
    platform: platformSchema.default("auto"),
    locale: z.string().trim().min(2).max(35).default("en"),
    targetValue: z.number().finite().positive().max(1_000_000).optional(),
    targetCurrency: z.string().trim().length(3).toUpperCase().optional(),
    landingPage: z.url({ protocol: /^https?$/ }).max(2_048).optional(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.targetCurrency && value.objective !== "revenue") {
      context.addIssue({
        code: "custom",
        path: ["targetCurrency"],
        message: "targetCurrency is only valid for revenue missions.",
      });
    }
  });

export const outcomeSchema = z
  .object({
    eventId: z.string().trim().min(8).max(128).regex(/^[A-Za-z0-9._:-]+$/),
    type: z.enum(["lead", "signup", "purchase", "revenue"]),
    quantity: z.number().finite().positive().max(1_000_000).default(1),
    value: z.number().finite().nonnegative().max(1_000_000_000).optional(),
    currency: z.string().trim().length(3).toUpperCase().optional(),
    occurredAt: z.iso.datetime({ offset: true }).optional(),
  })
  .strict()
  .superRefine((value, context) => {
    if (value.type === "revenue" && value.value === undefined) {
      context.addIssue({ code: "custom", path: ["value"], message: "Revenue outcomes require value." });
    }
    if (value.value !== undefined && !value.currency) {
      context.addIssue({ code: "custom", path: ["currency"], message: "currency is required with value." });
    }
  });

export const generatedMissionSchema = z
  .object({
    mission: z
      .object({
        title: z.string().trim().min(8).max(120),
        hypothesis: z.string().trim().min(20).max(500),
        audience: z.string().trim().min(3).max(160),
        primaryMetric: objectiveSchema,
        platform: resolvedPlatformSchema,
      })
      .strict(),
    asset: z
      .object({
        format: z.string().trim().min(2).max(80),
        title: z.string().trim().min(3).max(160),
        body: z.string().trim().min(30).max(40_000),
        cta: z.string().trim().min(3).max(240),
      })
      .strict(),
    evidence: z
      .array(
        z
          .object({
            id: z.string().regex(/^e[1-9][0-9]*$/),
            sectionId: z.string().regex(/^s[1-9][0-9]*$/),
            quote: z.string().min(3).max(1_200),
            confidence: z.number().min(0).max(1),
          })
          .strict(),
      )
      .min(1)
      .max(12),
    claimMap: z
      .array(
        z
          .object({
            claim: z.string().trim().min(3).max(500),
            evidenceIds: z.array(z.string().regex(/^e[1-9][0-9]*$/)).min(1).max(6),
          })
          .strict(),
      )
      .min(1)
      .max(20),
  })
  .strict();

export type CreateMissionInput = z.infer<typeof createMissionSchema>;
export type OutcomeInput = z.infer<typeof outcomeSchema>;
export type GeneratedMission = z.infer<typeof generatedMissionSchema>;
export type Objective = z.infer<typeof objectiveSchema>;
export type Platform = z.infer<typeof resolvedPlatformSchema>;

export type SemanticSection = {
  id: string;
  kind: "title" | "description" | "heading" | "paragraph" | "list" | "link" | "structured-data";
  text: string;
};

export type SourceEvidence = {
  finalUrl: string;
  digest: string;
  title: string;
  sections: SemanticSection[];
};
