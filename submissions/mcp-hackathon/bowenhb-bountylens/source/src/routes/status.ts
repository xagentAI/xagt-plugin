import type { FastifyInstance } from "fastify";

import type { AppConfig } from "../config.js";
import {
  healthResponseSchema,
  verificationResponseSchema,
} from "../schemas/status.js";

export type StatusRouteConfig = Pick<AppConfig, "projectSlug" | "sourceCommit">;

/** Register public liveness and immutable source-review proof endpoints. */
export function registerStatusRoutes(app: FastifyInstance, config: StatusRouteConfig): void {
  app.get("/health", async () =>
    healthResponseSchema.parse({
      status: "ok",
      commit: config.sourceCommit,
    }),
  );

  app.get("/.well-known/xagent-verification.json", async () =>
    verificationResponseSchema.parse({
      schemaVersion: 1,
      slug: config.projectSlug,
      commit: config.sourceCommit,
    }),
  );
}
