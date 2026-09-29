#!/usr/bin/env node
import { createServer } from '../src/http-server.mjs';

const portArg = process.argv.find((arg) => arg.startsWith('--port='));
const port = Number(portArg?.split('=')[1] ?? process.env.PORT ?? 8787);
const host = process.env.HOST ?? '127.0.0.1';

const server = createServer();

server.listen(port, host, () => {
  console.log(`Agent Acceptance Gate demo`);
  console.log(`Demo:   http://${host}:${port}/`);
  console.log(`Health: http://${host}:${port}/health`);
  console.log(`API:    POST http://${host}:${port}/audit-agent-deliverable`);
});
