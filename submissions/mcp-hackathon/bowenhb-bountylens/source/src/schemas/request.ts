import { z } from "zod";

const developerProfileSchema = z
  .object({
    languages: z.array(z.string().trim().min(1).max(50)).max(20).optional(),
    hourly_rate_usd: z.number().finite().positive().max(10_000).optional(),
    max_hours: z.number().finite().positive().max(10_000).optional(),
  })
  .strict();

/** Public input contract. URL semantics are validated by parseIssueUrl later. */
export const evaluateRequestSchema = z
  .object({
    issue_url: z.string().trim().min(1).max(2_048),
    developer_profile: developerProfileSchema.optional(),
  })
  .strict();

export type EvaluateRequest = z.infer<typeof evaluateRequestSchema>;
