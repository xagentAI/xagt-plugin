import type { Snapshot } from "./catalogue.js";
import {
  runCatalogue,
  runCatalogueDiff,
  runPlanCall,
  runQuote,
  runResolve,
  type Operation,
} from "./operations.js";
import { TOOLS } from "./tools.js";

/**
 * JSON-RPC 2.0 over one endpoint, so an agent runtime can list these tools and
 * call them without learning five REST paths.
 *
 * It is a thin layer on purpose. The tool list is derived from tools.json, the
 * same document served over HTTP, and each call dispatches into the same
 * operation the REST route uses. Nothing here decides anything: a second
 * description of a tool, or a second implementation of one, would be a second
 * thing to keep true.
 */

export const PROTOCOL_VERSION = "2025-06-18";

export type JsonRpcId = string | number | null;

export type JsonRpcRequest = {
  jsonrpc?: unknown;
  id?: JsonRpcId;
  method?: unknown;
  params?: unknown;
};

const PARSE_ERROR = -32700;
const INVALID_REQUEST = -32600;
const METHOD_NOT_FOUND = -32601;
const INVALID_PARAMS = -32602;

function ok(id: JsonRpcId, result: unknown) {
  return { jsonrpc: "2.0", id, result };
}

function fail(id: JsonRpcId, code: number, message: string, data?: unknown) {
  return { jsonrpc: "2.0", id, error: { code, message, ...(data === undefined ? {} : { data }) } };
}

type FieldSpec = { type?: string; required?: boolean; note?: string; default?: unknown };

/** JSON Schema for one tool, derived from the manifest rather than restated. */
function inputSchema(input: Record<string, FieldSpec> | undefined) {
  const properties: Record<string, unknown> = {};
  const required: string[] = [];

  for (const [name, spec] of Object.entries(input ?? {})) {
    const declared = spec.type ?? "string";
    const property =
      declared === "string[]"
        ? { type: "array", items: { type: "string" } }
        : { type: declared === "boolean" ? "boolean" : declared === "integer" ? "integer" : "string" };
    properties[name] = spec.note ? { ...property, description: spec.note } : property;
    if (spec.required) required.push(name);
  }

  return { type: "object", properties, ...(required.length ? { required } : {}) };
}

export function listTools() {
  return TOOLS.tools.map((tool) => ({
    name: tool.name,
    description: tool.purpose,
    inputSchema: inputSchema((tool as { input?: Record<string, FieldSpec> }).input),
  }));
}

export type McpContext = {
  snapshot: Snapshot;
  staleSeconds: number;
  submitted: Snapshot;
};

function dispatch(name: string, args: unknown, ctx: McpContext): Operation | null {
  switch (name) {
    case "plan_call":
      return runPlanCall(ctx.snapshot, ctx.staleSeconds, args);
    case "quote":
      return runQuote(ctx.snapshot, ctx.staleSeconds, args);
    case "resolve":
      return runResolve(ctx.snapshot, ctx.staleSeconds, args);
    case "catalogue":
      return runCatalogue(ctx.snapshot, ctx.staleSeconds, args);
    case "catalogue_diff":
      return runCatalogueDiff(ctx.submitted, ctx.snapshot);
    default:
      return null;
  }
}

/**
 * One request in, one response out. A request with no id is a notification and
 * gets nothing back, which the caller signals by receiving `null` here.
 */
export function handleRpc(request: JsonRpcRequest, ctx: McpContext): unknown | null {
  const id = (request.id ?? null) as JsonRpcId;
  const isNotification = request.id === undefined;

  if (request.jsonrpc !== "2.0" || typeof request.method !== "string") {
    return isNotification ? null : fail(id, INVALID_REQUEST, "A request carries jsonrpc 2.0 and a method name.");
  }

  const method = request.method;

  if (method === "initialize") {
    return isNotification
      ? null
      : ok(id, {
          protocolVersion: PROTOCOL_VERSION,
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: TOOLS.service, version: TOOLS.schemaVersion },
          instructions: TOOLS.description,
        });
  }

  // Sent after initialize; there is nothing to acknowledge.
  if (method === "notifications/initialized") return null;
  if (method === "ping") return isNotification ? null : ok(id, {});

  if (method === "tools/list") {
    return isNotification ? null : ok(id, { tools: listTools() });
  }

  if (method === "tools/call") {
    if (isNotification) return null;
    const params = (request.params ?? {}) as { name?: unknown; arguments?: unknown };
    if (typeof params.name !== "string") {
      return fail(id, INVALID_PARAMS, "tools/call needs a tool name in params.name.");
    }
    const outcome = dispatch(params.name, params.arguments ?? {}, ctx);
    if (!outcome) {
      return fail(id, INVALID_PARAMS, `No tool is called ${params.name}.`, {
        available: TOOLS.tools.map((t) => t.name),
      });
    }
    // A tool that refuses is not a protocol failure: the request was
    // well formed and the answer is the refusal, carried where a caller reads
    // results. Malformed JSON-RPC is what the error object above is for.
    return ok(id, {
      content: [{ type: "text", text: JSON.stringify(outcome.body, null, 2) }],
      ...(outcome.status >= 400 ? { isError: true } : {}),
    });
  }

  return isNotification ? null : fail(id, METHOD_NOT_FOUND, `This server has no method ${method}.`);
}

/** The whole endpoint: one request or a batch, per JSON-RPC 2.0. */
export function handleMcpPayload(payload: unknown, ctx: McpContext): unknown | null {
  if (Array.isArray(payload)) {
    if (payload.length === 0) {
      return fail(null, INVALID_REQUEST, "An empty batch is not a request.");
    }
    const replies = payload
      .map((entry) => handleRpc((entry ?? {}) as JsonRpcRequest, ctx))
      .filter((reply): reply is unknown => reply !== null);
    return replies.length ? replies : null;
  }

  if (!payload || typeof payload !== "object") {
    return fail(null, INVALID_REQUEST, "A request is a JSON object or an array of them.");
  }

  return handleRpc(payload as JsonRpcRequest, ctx);
}

export const PARSE_ERROR_RESPONSE = (detail: string) =>
  fail(null, PARSE_ERROR, "The request body is not valid JSON.", detail);
