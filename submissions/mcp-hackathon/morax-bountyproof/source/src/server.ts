import { createServer, type IncomingMessage } from "node:http";
import { Readable } from "node:stream";
import { createService, type ServiceConfig } from "./service.js";

const port = Number.parseInt(process.env.PORT ?? "8787", 10);
const host = process.env.HOST ?? "127.0.0.1";
if (!Number.isInteger(port) || port < 1 || port > 65_535) throw new Error("PORT must be from 1 to 65535.");

const config: ServiceConfig = {
  reviewCommit: process.env.REVIEW_COMMIT ?? "development",
  sourceRepository: process.env.SOURCE_REPOSITORY ?? "https://github.com/fzlzjerry/bountyproof",
  ...(process.env.GITHUB_API_TOKEN ? { githubApiToken: process.env.GITHUB_API_TOKEN } : {}),
};
const service = createService(config);

type StreamingRequestInit = RequestInit & { duplex?: "half" };

function webRequest(request: IncomingMessage): Request {
  const authority = request.headers.host ?? `${host}:${port}`;
  const protocol = request.headers["x-forwarded-proto"] === "https" ? "https" : "http";
  const url = new URL(request.url ?? "/", `${protocol}://${authority}`);
  const method = request.method ?? "GET";
  const init: StreamingRequestInit = { method, headers: request.headers as HeadersInit };
  if (method !== "GET" && method !== "HEAD") {
    init.body = Readable.toWeb(request) as ReadableStream<Uint8Array>;
    init.duplex = "half";
  }
  return new Request(url, init);
}

const server = createServer({ maxHeaderSize: 16 * 1024 }, async (request, response) => {
  const startedAt = performance.now();
  const result = await service(webRequest(request));
  response.statusCode = result.status;
  for (const [name, value] of result.headers) response.setHeader(name, value);
  const body = result.body ? Buffer.from(await result.arrayBuffer()) : null;
  response.end(body);
  console.log(JSON.stringify({
    level: "info",
    event: "request",
    method: request.method,
    path: new URL(request.url ?? "/", "http://localhost").pathname,
    status: result.status,
    durationMs: Math.round(performance.now() - startedAt),
  }));
});

server.on("error", (error) => {
  const code = "code" in error && typeof error.code === "string" ? error.code : "UNKNOWN";
  console.error(JSON.stringify({ level: "error", event: "server_error", code, message: error.message }));
  process.exitCode = 1;
});

server.requestTimeout = 12_000;
server.headersTimeout = 13_000;
server.keepAliveTimeout = 5_000;
server.listen(port, host, () => {
  console.log(JSON.stringify({
    level: "info",
    event: "listening",
    address: `http://${host}:${port}`,
    reviewCommit: config.reviewCommit,
  }));
});

function shutdown(signal: string) {
  console.log(JSON.stringify({ level: "info", event: "shutdown", signal }));
  server.close((error) => {
    if (error) {
      console.error(error);
      process.exitCode = 1;
    }
  });
}

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
