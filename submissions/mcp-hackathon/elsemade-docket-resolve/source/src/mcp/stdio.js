import { serveStdio } from "@modelcontextprotocol/server/stdio";

import { createDocketMcpServer } from "./server.js";

serveStdio(() => createDocketMcpServer(), {
  onerror(error) {
    process.stderr.write(`${JSON.stringify({ level: "error", event: "mcp_stdio_error", message: error.message })}\n`);
  },
});
