import { buildApp } from "./app.js";
import { loadConfig } from "./config.js";

// Keep network startup outside buildApp so tests can exercise the same routes
// in memory without reserving a local port.
const config = loadConfig();
const app = await buildApp(config);

try {
  await app.listen({
    host: config.host,
    port: config.port,
  });
} catch (error) {
  // Fastify's structured logger preserves useful startup diagnostics while the
  // non-zero exit code tells deployment platforms that the service failed.
  app.log.error(error);
  process.exitCode = 1;
}
