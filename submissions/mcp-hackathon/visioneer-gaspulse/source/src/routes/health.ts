import type { FastifyInstance } from "fastify";
import { GIT_COMMIT } from "../config.js";

export async function registerHealthRoute(app: FastifyInstance): Promise<void> {
  app.get("/health", async () => ({ status: "ok", commit: GIT_COMMIT }));
}
