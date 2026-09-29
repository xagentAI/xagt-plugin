import { createServer } from "node:http";

import { deploymentConfig } from "./config.js";
import { createRequestHandler } from "./http.js";

const port = Number.parseInt(process.env.PORT ?? "3000", 10);
const host = process.env.HOST ?? "0.0.0.0";
const config = deploymentConfig();
export const server = createServer(createRequestHandler(config));

if (!process.env.VERCEL) {
  server.listen(port, host, () => {
    console.log(JSON.stringify({
      level: "info",
      event: "server_started",
      host,
      port,
      commit: config.commit,
      slug: config.slug,
    }));
  });

  function shutdown(signal) {
    console.log(JSON.stringify({ level: "info", event: "shutdown", signal }));
    server.close((error) => {
      process.exitCode = error ? 1 : 0;
    });
  }

  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

export default server;
