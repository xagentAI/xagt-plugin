/**
 * X-Agent verification document (official deployment-proof schema).
 *
 *   { "schemaVersion": 1, "slug": "modolu-settle", "commit": "<40-hex reviewed commit>" }
 *
 * This module is the ONLY place that knows the document's shape. The slug is
 * fixed for this project; `XAGENT_SLUG` stays a deployment variable
 * (ARCHITECTURE.md §11, §18) but any value other than the registered slug is
 * a configuration error, never silently served. The commit is the same
 * `VERCEL_GIT_COMMIT_SHA` that `/health` reports; when it is unavailable or
 * malformed the route fails with 500 rather than fabricating evidence.
 */
import { z } from "zod";

import type { AppConfig } from "./config";
import { AppError } from "./errors";

/** Registered X-Agent MCP Hackathon slug for Settle. */
export const XAGENT_SLUG = "modolu-settle";
export const XAGENT_SCHEMA_VERSION = 1;

export const xagentVerificationSchema = z
  .object({
    schemaVersion: z.literal(XAGENT_SCHEMA_VERSION),
    slug: z.literal(XAGENT_SLUG),
    commit: z.string().regex(/^[0-9a-f]{40}$/),
  })
  .strict();

export type XagentVerification = z.infer<typeof xagentVerificationSchema>;

/**
 * Builds the verification document, or throws `INTERNAL_ERROR` when the slug
 * is missing or not the registered one, or the commit is unavailable.
 */
export function buildXagentVerification(
  config: Pick<AppConfig, "xagentSlug" | "commitSha">,
): XagentVerification {
  const missing: string[] = [];
  if (config.xagentSlug === null) {
    missing.push("XAGENT_SLUG");
  }
  if (config.commitSha === null) {
    missing.push("VERCEL_GIT_COMMIT_SHA");
  }
  if (missing.length > 0) {
    throw new AppError(
      "INTERNAL_ERROR",
      `X-Agent verification is not configured: missing ${missing.join(", ")}`,
      { context: { missing } },
    );
  }
  if (config.xagentSlug !== XAGENT_SLUG) {
    throw new AppError("INTERNAL_ERROR", `X-Agent verification is misconfigured: XAGENT_SLUG must be "${XAGENT_SLUG}"`, {
      context: { configuredSlug: config.xagentSlug },
    });
  }

  return xagentVerificationSchema.parse({
    schemaVersion: XAGENT_SCHEMA_VERSION,
    slug: config.xagentSlug,
    commit: config.commitSha,
  });
}
