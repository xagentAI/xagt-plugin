import "dotenv/config";
import Fastify from "fastify";
import { PORT } from "./config.js";
import { registerHealthRoute } from "./routes/health.js";
import { registerVerificationRoute } from "./routes/verification.js";
import { registerActivityRoute } from "./routes/activity.js";
import { registerGasCurrentRoute } from "./routes/gasCurrent.js";

export async function buildServer() {
  const app = Fastify({ logger: true });

  await registerHealthRoute(app);
  await registerVerificationRoute(app);
  await registerActivityRoute(app);
  await registerGasCurrentRoute(app);

  app.setNotFoundHandler((_request, reply) => {
    reply.code(404).send({ error: { code: "not_found", message: "no route matches this path" } });
  });

  return app;
}

async function main() {
  const app = await buildServer();
  try {
    await app.listen({ port: PORT, host: "0.0.0.0" });
  } catch (error) {
    app.log.error(error);
    process.exit(1);
  }
}

if (process.env.VITEST !== "true") {
  void main();
}
