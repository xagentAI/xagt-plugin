import { authenticate } from "./auth";
import { AppError, asAppError } from "./errors";
import { createMissionOperation, getMissionOperation, recordOutcomeOperation } from "./mission";
import { createMissionSchema, outcomeSchema } from "./schemas";
import { z } from "zod";

const createToolArguments = createMissionSchema.extend({
  idempotencyKey: z.string().min(8).max(128).regex(/^[A-Za-z0-9._:-]+$/),
});
const getToolArguments = z.object({ missionId: z.string().regex(/^gm_[a-z0-9]{24}$/) }).strict();
const outcomeToolArguments = outcomeSchema.and(
  z.object({
    missionId: z.string().regex(/^gm_[a-z0-9]{24}$/),
    idempotencyKey: z.string().min(8).max(128).regex(/^[A-Za-z0-9._:-]+$/),
  }),
);

const TOOLS = [
  {
    name: "finfold_create_growth_mission",
    title: "Create a Finfold growth mission",
    description:
      "Reads one public business URL and creates one evidence-bound growth mission, one platform-native content asset, and one tracked CTA. Mutation: persists the mission. It never publishes content or modifies an external account. Requires mission:create. Retry only with the same idempotencyKey.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["sourceUrl", "objective", "idempotencyKey"],
      properties: {
        sourceUrl: { type: "string", format: "uri", description: "Public HTTP(S) business page." },
        objective: { type: "string", enum: ["leads", "signups", "purchases", "revenue"] },
        platform: { type: "string", enum: ["auto", "linkedin", "x", "reddit", "xiaohongshu", "wechat"], default: "auto" },
        locale: { type: "string", default: "en" },
        targetValue: { type: "number", exclusiveMinimum: 0 },
        landingPage: { type: "string", format: "uri" },
        idempotencyKey: { type: "string", minLength: 8, maxLength: 128 },
      },
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: true },
  },
  {
    name: "finfold_get_growth_mission",
    title: "Get a Finfold growth mission",
    description:
      "Reads a persisted mission, its anonymous attribution totals, verdict, and next action. Read-only with no side effects. Requires mission:read.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["missionId"],
      properties: { missionId: { type: "string", pattern: "^gm_[a-z0-9]{24}$" } },
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
  {
    name: "finfold_record_growth_outcome",
    title: "Record a Finfold growth outcome",
    description:
      "Records one attributable lead, signup, purchase, or revenue event and recomputes the verdict. Mutation: writes one idempotent outcome. No external side effects. Requires outcome:write. Retry with the same eventId and idempotencyKey.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["missionId", "idempotencyKey", "eventId", "type"],
      properties: {
        missionId: { type: "string", pattern: "^gm_[a-z0-9]{24}$" },
        idempotencyKey: { type: "string", minLength: 8, maxLength: 128 },
        eventId: { type: "string", minLength: 8, maxLength: 128 },
        type: { type: "string", enum: ["lead", "signup", "purchase", "revenue"] },
        quantity: { type: "number", exclusiveMinimum: 0, default: 1 },
        value: { type: "number", minimum: 0 },
        currency: { type: "string", minLength: 3, maxLength: 3 },
        occurredAt: { type: "string", format: "date-time" },
      },
    },
    annotations: { readOnlyHint: false, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  },
] as const;

type JsonRpcId = string | number | null;
type JsonRpcRequest = { jsonrpc: "2.0"; id?: JsonRpcId; method: string; params?: unknown };

function rpcResult(id: JsonRpcId, result: unknown): Record<string, unknown> {
  return { jsonrpc: "2.0", id, result };
}

function rpcError(id: JsonRpcId, code: number, message: string, data?: unknown): Record<string, unknown> {
  return { jsonrpc: "2.0", id, error: { code, message, ...(data === undefined ? {} : { data }) } };
}

function toolResult(value: unknown): Record<string, unknown> {
  return {
    content: [{ type: "text", text: JSON.stringify(value) }],
    structuredContent: value,
    isError: false,
  };
}

function toolError(error: unknown, requestId: string): Record<string, unknown> {
  const appError =
    error instanceof z.ZodError
      ? new AppError("INVALID_REQUEST", "Tool arguments failed validation.", 400, {
          details: { issues: error.issues.map((issue) => ({ path: issue.path.join("."), message: issue.message })) },
        })
      : asAppError(error);
  const value = {
    error: { code: appError.code, message: appError.message, retryable: appError.retryable, requestId },
  };
  return {
    content: [{ type: "text", text: JSON.stringify(value) }],
    structuredContent: value,
    isError: true,
  };
}

function parseRpc(value: unknown): JsonRpcRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new AppError("INVALID_REQUEST", "JSON-RPC request must be an object.", 400);
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.jsonrpc !== "2.0" || typeof candidate.method !== "string") {
    throw new AppError("INVALID_REQUEST", "Invalid JSON-RPC 2.0 request.", 400);
  }
  if (
    candidate.id !== undefined &&
    candidate.id !== null &&
    typeof candidate.id !== "string" &&
    typeof candidate.id !== "number"
  ) {
    throw new AppError("INVALID_REQUEST", "JSON-RPC id must be a string, number, or null.", 400);
  }
  return candidate as JsonRpcRequest;
}

export async function handleMcp(request: Request, env: Env, body: unknown, requestId: string): Promise<Response> {
  let rpc: JsonRpcRequest;
  try {
    rpc = parseRpc(body);
  } catch (error) {
    return Response.json(rpcError(null, -32600, "Invalid Request", toolError(error, requestId)), { status: 400 });
  }

  const id = rpc.id ?? null;
  if (rpc.method.startsWith("notifications/")) return new Response(null, { status: 202 });
  if (rpc.method === "ping") return Response.json(rpcResult(id, {}));
  if (rpc.method === "initialize") {
    const requested = (rpc.params as { protocolVersion?: unknown } | undefined)?.protocolVersion;
    const protocolVersion = requested === "2025-03-26" ? "2025-03-26" : "2025-11-25";
    return Response.json(
      rpcResult(id, {
        protocolVersion,
        capabilities: { tools: { listChanged: false } },
        serverInfo: { name: "finfold-growth-mission", title: "Finfold Growth Mission API", version: "1.0.0" },
        instructions:
          "Create one evidence-bound mission, use its tracked CTA, then record real outcomes. The server never auto-publishes.",
      }),
    );
  }

  if (rpc.method === "tools/list") {
    try {
      const auth = await authenticate(request, env);
      const tools = TOOLS.filter((tool) => {
        if (tool.name === "finfold_create_growth_mission") return auth.scopes.has("mission:create");
        if (tool.name === "finfold_get_growth_mission") return auth.scopes.has("mission:read");
        return auth.scopes.has("outcome:write");
      });
      return Response.json(rpcResult(id, { tools }));
    } catch (error) {
      return Response.json(rpcError(id, -32001, "Authentication failed", toolError(error, requestId)), { status: 401 });
    }
  }

  if (rpc.method !== "tools/call") return Response.json(rpcError(id, -32601, "Method not found"), { status: 404 });
  const params = rpc.params as { name?: unknown; arguments?: unknown } | undefined;
  if (!params || typeof params.name !== "string") {
    return Response.json(rpcError(id, -32602, "Invalid params"), { status: 400 });
  }

  try {
    if (params.name === "finfold_create_growth_mission") {
      const auth = await authenticate(request, env, "mission:create");
      const parsed = createToolArguments.parse(params.arguments ?? {});
      const { idempotencyKey, ...input } = parsed;
      const result = await createMissionOperation(env, auth, input, idempotencyKey, requestId);
      return Response.json(rpcResult(id, toolResult(JSON.parse(result.body))));
    }
    if (params.name === "finfold_get_growth_mission") {
      const auth = await authenticate(request, env, "mission:read");
      const parsed = getToolArguments.parse(params.arguments ?? {});
      const result = await getMissionOperation(env, auth, parsed.missionId);
      return Response.json(rpcResult(id, toolResult(result)));
    }
    if (params.name === "finfold_record_growth_outcome") {
      const auth = await authenticate(request, env, "outcome:write");
      const parsed = outcomeToolArguments.parse(params.arguments ?? {});
      const { missionId, idempotencyKey, ...input } = parsed;
      const result = await recordOutcomeOperation(env, auth, missionId, input, idempotencyKey);
      return Response.json(rpcResult(id, toolResult(JSON.parse(result.body))));
    }
    return Response.json(rpcError(id, -32602, `Unknown tool: ${params.name}`), { status: 400 });
  } catch (error) {
    return Response.json(rpcResult(id, toolError(error, requestId)));
  }
}
