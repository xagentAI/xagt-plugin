import { z } from "zod";

const commitSchema = z.string().regex(/^[0-9a-f]{40}$/i);

export const healthResponseSchema = z
  .object({
    status: z.literal("ok"),
    commit: commitSchema,
  })
  .strict();

export const verificationResponseSchema = z
  .object({
    schemaVersion: z.literal(1),
    slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/),
    commit: commitSchema,
  })
  .strict();

export type HealthResponse = z.infer<typeof healthResponseSchema>;
export type VerificationResponse = z.infer<typeof verificationResponseSchema>;
