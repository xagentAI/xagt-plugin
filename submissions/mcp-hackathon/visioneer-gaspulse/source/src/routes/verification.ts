import type { FastifyInstance } from "fastify";
import { GIT_COMMIT, SUBMISSION_SLUG } from "../config.js";

export async function registerVerificationRoute(app: FastifyInstance): Promise<void> {
  app.get("/.well-known/xagent-verification.json", async () => ({
    schemaVersion: 1,
    slug: SUBMISSION_SLUG,
    commit: GIT_COMMIT,
  }));
}
