import { z } from "zod";

export const publicErrorCodeSchema = z.enum([
  "INVALID_REQUEST",
  "INVALID_ISSUE_URL",
  "REQUEST_TOO_LARGE",
  "EXAMPLE_NOT_FOUND",
  "ISSUE_NOT_FOUND",
  "GITHUB_RATE_LIMITED",
  "UPSTREAM_TIMEOUT",
  "EVALUATION_FAILED",
]);

export const errorResponseSchema = z
  .object({
    request_id: z.string().min(1).max(128),
    error: z
      .object({
        code: publicErrorCodeSchema,
        message: z.string().min(1),
        retryable: z.boolean(),
        retry_after_seconds: z.number().int().nonnegative().optional(),
      })
      .strict(),
  })
  .strict();

export type PublicErrorCode = z.infer<typeof publicErrorCodeSchema>;
export type ErrorResponse = z.infer<typeof errorResponseSchema>;

export function createErrorResponse(
  requestId: string,
  code: PublicErrorCode,
  message: string,
  retryable: boolean,
  retryAfterSeconds?: number,
): ErrorResponse {
  return errorResponseSchema.parse({
    request_id: requestId,
    error: {
      code,
      message,
      retryable,
      ...(retryAfterSeconds === undefined ? {} : { retry_after_seconds: retryAfterSeconds }),
    },
  });
}
