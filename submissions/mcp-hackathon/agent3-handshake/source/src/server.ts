/**
 * Two doors onto the same five operations, plus the three endpoints the
 * hackathon's verification requires (health, well-known, API) on one origin.
 */

import { createServer } from "node:http";
import {
  auditRegistry,
  cacheStats,
  describeEntry,
  paymentReadings,
  planCall,
  registrySnapshot,
} from "./operations.js";
import { TOOLS, inputSchema, toolByName } from "./tools.js";

const PORT = Number(process.env.PORT ?? 8080);
const COMMIT = process.env.REVIEW_COMMIT ?? "0".repeat(40);
const SLUG = "agent3-handshake";

function send(res: import("node:http").ServerResponse, status: number, body: unknown) {
  const payload = JSON.stringify(body, null, 2);
  res.writeHead(status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "content-type",
  });
  res.end(payload);
}

/** Upstream failures are reported, never smoothed into a partial answer. */
function upstreamError(error: unknown) {
  return {
    error: "upstream_unavailable",
    detail: error instanceof Error ? error.message : String(error),
  };
}

async function readBody(req: import("node:http").IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of req) chunks.push(chunk as Buffer);
  if (chunks.length === 0) return undefined;
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

/** Runs one tool by name. Shared by REST and MCP so they cannot diverge. */
async function runTool(name: string, args: Record<string, unknown>) {
  switch (name) {
    case "registry_audit":
      return { ok: true as const, data: await auditRegistry() };
    case "entry_describe": {
      const entry = args.entry;
      if (typeof entry !== "string" || entry.length === 0) {
        return { ok: false as const, code: "invalid_params", detail: 'string "entry" is required' };
      }
      const result = await describeEntry(entry);
      if (!result.found) return { ok: false as const, code: "entry_not_found", detail: result };
      return { ok: true as const, data: result };
    }
    case "call_plan": {
      const entry = args.entry;
      const operation = args.operation;
      if (typeof entry !== "string" || typeof operation !== "string") {
        return {
          ok: false as const,
          code: "invalid_params",
          detail: 'strings "entry" and "operation" are required',
        };
      }
      const result = await planCall(entry, operation);
      if (!result.found) return { ok: false as const, code: "entry_not_found", detail: result };
      if (!result.ok) return { ok: false as const, code: "not_callable", detail: result.refusal };
      return { ok: true as const, data: result.spec };
    }
    case "payment_readings":
      return { ok: true as const, data: await paymentReadings() };
    case "registry_snapshot":
      return { ok: true as const, data: await registrySnapshot() };
    default:
      return { ok: false as const, code: "unknown_tool", detail: `no tool named "${name}"` };
  }
}

const server = createServer(async (req, res) => {
  // Behind a TLS-terminating proxy the socket is plain http, so the scheme has
  // to come from the forwarded header. Deriving it from the socket would make
  // every self-reported URL say http:// on a service that is only reachable
  // over https, which the event's verifier rejects and a reader would read as
  // a broken deployment.
  const forwardedProto = String(req.headers["x-forwarded-proto"] ?? "").split(",")[0]!.trim();
  const scheme = forwardedProto === "https" || forwardedProto === "http" ? forwardedProto : "http";
  const url = new URL(req.url ?? "/", `${scheme}://${req.headers.host ?? "localhost"}`);
  const path = url.pathname.replace(/\/+$/, "") || "/";

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "access-control-allow-origin": "*",
      "access-control-allow-headers": "content-type",
      "access-control-allow-methods": "GET,POST,OPTIONS",
    });
    res.end();
    return;
  }

  try {
    if (path === "/health") {
      let upstream: unknown = null;
      try {
        upstream = await registrySnapshot();
      } catch (error) {
        upstream = upstreamError(error);
      }
      send(res, 200, { status: "ok", commit: COMMIT, slug: SLUG, upstream, cache: cacheStats() });
      return;
    }

    if (path === "/.well-known/xagent-verification.json") {
      send(res, 200, {
        // schemaVersion, slug and commit are the three fields the event's
        // verifier compares against submission.json. Keep them first and keep
        // them exact.
        schemaVersion: 1,
        slug: SLUG,
        commit: COMMIT,
        apiBaseUrl: `${url.origin}/v1`,
        healthCheckUrl: `${url.origin}/health`,
        mcpEndpoint: `${url.origin}/mcp`,
        tools: TOOLS.map((tool) => tool.name),
      });
      return;
    }

    if (path === "/" || path === "/v1") {
      send(res, 200, {
        slug: SLUG,
        commit: COMMIT,
        description:
          "Turns an Agent3 registry entry into the request an agent would actually send, and names every field that stops it.",
        tools: TOOLS.map((tool) => ({
          name: tool.name,
          title: tool.title,
          rest: `${tool.restMethod} ${tool.restPath}`,
        })),
        mcp: `POST ${url.origin}/mcp`,
      });
      return;
    }

    if (path === "/mcp" && req.method === "POST") {
      let body: Record<string, unknown>;
      try {
        body = (await readBody(req)) as Record<string, unknown>;
      } catch {
        send(res, 200, {
          jsonrpc: "2.0",
          id: null,
          error: { code: -32700, message: "Parse error" },
        });
        return;
      }
      const id = (body?.id as string | number | null) ?? null;
      const method = body?.method;

      if (method === "initialize") {
        send(res, 200, {
          jsonrpc: "2.0",
          id,
          result: {
            protocolVersion: "2025-06-18",
            capabilities: { tools: {} },
            serverInfo: { name: SLUG, version: COMMIT.slice(0, 12) },
          },
        });
        return;
      }

      if (method === "tools/list") {
        send(res, 200, {
          jsonrpc: "2.0",
          id,
          result: {
            tools: TOOLS.map((tool) => ({
              name: tool.name,
              description: tool.description,
              inputSchema: inputSchema(tool),
            })),
          },
        });
        return;
      }

      if (method === "tools/call") {
        const params = (body?.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
        const name = params.name ?? "";
        if (!toolByName(name)) {
          // Unknown tool is a protocol-level invalid param, distinct from a
          // tool that ran and declined.
          send(res, 200, {
            jsonrpc: "2.0",
            id,
            error: { code: -32602, message: `Unknown tool: ${name}` },
          });
          return;
        }
        let outcome: Awaited<ReturnType<typeof runTool>>;
        try {
          outcome = await runTool(name, params.arguments ?? {});
        } catch (error) {
          send(res, 200, {
            jsonrpc: "2.0",
            id,
            result: {
              isError: true,
              content: [{ type: "text", text: JSON.stringify(upstreamError(error), null, 2) }],
            },
          });
          return;
        }
        // A tool that ran and refused reports through isError, not through a
        // JSON-RPC error: the caller asked a valid question and got an answer.
        send(res, 200, {
          jsonrpc: "2.0",
          id,
          result: {
            isError: !outcome.ok,
            content: [
              {
                type: "text",
                text: JSON.stringify(outcome.ok ? outcome.data : outcome, null, 2),
              },
            ],
          },
        });
        return;
      }

      send(res, 200, {
        jsonrpc: "2.0",
        id,
        error: { code: -32601, message: `Method not found: ${String(method)}` },
      });
      return;
    }

    const tool = TOOLS.find((candidate) => candidate.restPath === path);
    if (tool) {
      const args: Record<string, unknown> = {};
      for (const key of Object.keys(tool.input)) {
        const value = url.searchParams.get(key);
        if (value !== null) args[key] = value;
      }
      const outcome = await runTool(tool.name, args);
      if (outcome.ok) send(res, 200, outcome.data);
      else send(res, outcome.code === "invalid_params" ? 400 : 404, outcome);
      return;
    }

    send(res, 404, { error: "not_found", path });
  } catch (error) {
    send(res, 502, upstreamError(error));
  }
});

server.listen(PORT, () => {
  process.stdout.write(`${SLUG} listening on ${PORT} at commit ${COMMIT}\n`);
});
