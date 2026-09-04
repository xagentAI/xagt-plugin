import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { route, send } from "./http.js";

const ROOT = dirname(fileURLToPath(import.meta.url));

function loadCommit() {
  if (process.env.REVIEW_COMMIT) return process.env.REVIEW_COMMIT;
  try {
    return readFileSync(join(ROOT, "..", "COMMIT"), "utf8").trim();
  } catch {
    return "0".repeat(40);
  }
}

const commit = loadCommit();
const port = Number(process.env.PORT || 8787);

const server = createServer((req, res) => {
  try {
    const host = req.headers.host || "127.0.0.1";
    const url = new URL(req.url || "/", `http://${host}`);
    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "access-control-allow-origin": "*",
        "access-control-allow-methods": "GET, OPTIONS",
        "access-control-allow-headers": "content-type"
      });
      res.end();
      return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      send(res, { status: 405, body: { error: "method_not_allowed", message: "GET only" } });
      return;
    }
    const result = route(url, { commit });
    if (req.method === "HEAD") {
      res.writeHead(result.status, { "content-type": "application/json; charset=utf-8" });
      res.end();
      return;
    }
    send(res, result);
  } catch (error) {
    send(res, { status: 500, body: { error: "internal", message: error instanceof Error ? error.message : String(error) } });
  }
});

server.listen(port, () => {
  process.stdout.write(`VenueClock listening on http://127.0.0.1:${port} commit=${commit}\n`);
});
