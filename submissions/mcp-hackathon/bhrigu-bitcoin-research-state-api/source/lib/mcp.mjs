import { buildState } from "./state.mjs";
import { getWindow, listWindows } from "./windows.mjs";

export const MCP_MODERN_PROTOCOL_VERSION = "2026-07-28";
export const MCP_LEGACY_PROTOCOL_VERSION = "2025-11-25";
export const MCP_SUPPORTED_PROTOCOL_VERSIONS = Object.freeze([
  MCP_MODERN_PROTOCOL_VERSION,
  MCP_LEGACY_PROTOCOL_VERSION,
  "2025-03-26"
]);
export const MCP_PROTOCOL_VERSION = MCP_LEGACY_PROTOCOL_VERSION;

const SERVER_INFO = Object.freeze({
  name: "bhrigu-bitcoin-research-state-api",
  title: "BHRIGU Bitcoin Temporal Evidence",
  version: "0.2.0"
});
const SERVER_CAPABILITIES = Object.freeze({ tools: Object.freeze({ listChanged: false }) });
const SERVER_INSTRUCTIONS = "Use frozen windows to ask what was known then, compare with public reality now, and inspect durable evidence. Read-only research only; no trading or financial authority.";
const CACHE_HINT = Object.freeze({ ttlMs: 300000, cacheScope: "public" });
const PROTOCOL_META = "io.modelcontextprotocol/protocolVersion";
const CLIENT_INFO_META = "io.modelcontextprotocol/clientInfo";
const CLIENT_CAPS_META = "io.modelcontextprotocol/clientCapabilities";
const SERVER_INFO_META = "io.modelcontextprotocol/serverInfo";

export const MCP_TOOLS = Object.freeze([
  {
    name: "bhrigu_get_bitcoin_research_state",
    title: "Get live Bitcoin research state",
    description: "Read the current BTCUSDT market state, Bitcoin protocol-time coordinates, source freshness, and temporal-evidence summary. Read-only; never trades, signs, pays, transfers, or accesses private account data.",
    inputSchema: { type: "object", additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true }
  },
  {
    name: "bhrigu_list_temporal_windows",
    title: "List BHRIGU temporal windows",
    description: "List public precommitted Bitcoin observation windows with phase, boundary, immutable-rewrite law, and durable evidence count.",
    inputSchema: { type: "object", additionalProperties: false, properties: {} },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  },
  {
    name: "bhrigu_get_temporal_window",
    title: "Get one temporal window and evidence",
    description: "Read one frozen precommit together with durable post-boundary evidence already committed for that window.",
    inputSchema: {
      type: "object", additionalProperties: false, required: ["window_id"],
      properties: { window_id: { type: "string", enum: ["SEP_10_2026", "SEP_17_2026"] } }
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }
  },
  {
    name: "bhrigu_compare_window_to_reality",
    title: "Compare a precommit with live reality",
    description: "Read live public Bitcoin evidence and compare BTCUSDT against the selected precommitted baseline. No observation is written and no trading authority exists.",
    inputSchema: {
      type: "object", additionalProperties: false, required: ["window_id"],
      properties: { window_id: { type: "string", enum: ["SEP_10_2026", "SEP_17_2026"] } }
    },
    annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true }
  }
]);

const rpcResult = (id, result) => ({ jsonrpc: "2.0", id, result });
const rpcError = (id, code, message, data) => ({
  jsonrpc: "2.0", id, error: { code, message, ...(data === undefined ? {} : { data }) }
});
const modernMeta = () => ({ [SERVER_INFO_META]: SERVER_INFO });
const completeResult = (value = {}, modern = false, cacheable = false) => modern
  ? { resultType: "complete", ...value, ...(cacheable ? CACHE_HINT : {}), _meta: modernMeta() }
  : value;
const toolResult = (value, modern = false) => completeResult({
  content: [{ type: "text", text: JSON.stringify(value) }],
  structuredContent: value,
  isError: false
}, modern);
const toolError = (code, message, modern = false) => completeResult({
  content: [{ type: "text", text: JSON.stringify({ error: { code, message } }) }],
  structuredContent: { error: { code, message } },
  isError: true
}, modern);

function parseRpc(body) {
  if (!body || typeof body !== "object" || Array.isArray(body) || body.jsonrpc !== "2.0" || typeof body.method !== "string") return null;
  if (body.id !== undefined && body.id !== null && typeof body.id !== "string" && typeof body.id !== "number") return null;
  return body;
}

function parseWindowId(args) {
  const id = args?.window_id;
  return typeof id === "string" ? id : null;
}

function bodyProtocolVersion(rpc) {
  return rpc.params?._meta?.[PROTOCOL_META] ?? null;
}

function unsupportedVersion(rpc, requested) {
  return rpcError(rpc.id ?? null, -32022, "Unsupported protocol version", {
    supported: MCP_SUPPORTED_PROTOCOL_VERSIONS,
    requested
  });
}

function classifyEra(rpc, transportMeta = {}) {
  const bodyVersion = bodyProtocolVersion(rpc);
  const headerVersion = transportMeta.protocolVersion ?? null;

  if (bodyVersion && !MCP_SUPPORTED_PROTOCOL_VERSIONS.includes(bodyVersion)) {
    return { error: unsupportedVersion(rpc, bodyVersion) };
  }
  if (headerVersion && !MCP_SUPPORTED_PROTOCOL_VERSIONS.includes(headerVersion)) {
    return { error: unsupportedVersion(rpc, headerVersion) };
  }

  const modern = rpc.method === "server/discover"
    || bodyVersion !== null
    || headerVersion === MCP_MODERN_PROTOCOL_VERSION;
  return { modern, bodyVersion, headerVersion };
}

function validImplementation(value) {
  return value
    && typeof value === "object"
    && !Array.isArray(value)
    && typeof value.name === "string"
    && value.name.length > 0
    && typeof value.version === "string"
    && value.version.length > 0;
}

function validateModernRequest(rpc, transportMeta = {}, classification) {
  const envelope = rpc.params?._meta;
  if (!envelope || typeof envelope !== "object" || Array.isArray(envelope)) {
    return rpcError(rpc.id ?? null, -32602, "Invalid params", {
      missing: [PROTOCOL_META, CLIENT_CAPS_META]
    });
  }

  const version = envelope[PROTOCOL_META];
  if (typeof version !== "string" || version.length === 0) {
    return rpcError(rpc.id ?? null, -32602, "Invalid params", { missing: [PROTOCOL_META] });
  }
  if (version !== MCP_MODERN_PROTOCOL_VERSION) return unsupportedVersion(rpc, version);

  const clientCapabilities = envelope[CLIENT_CAPS_META];
  if (!clientCapabilities || typeof clientCapabilities !== "object" || Array.isArray(clientCapabilities)) {
    return rpcError(rpc.id ?? null, -32602, "Invalid params", { missing: [CLIENT_CAPS_META] });
  }

  const clientInfo = envelope[CLIENT_INFO_META];
  if (clientInfo !== undefined && !validImplementation(clientInfo)) {
    return rpcError(rpc.id ?? null, -32602, "Invalid params", { malformed: [CLIENT_INFO_META] });
  }

  const isNotification = rpc.method.startsWith("notifications/");
  if (transportMeta.requireHeaders && !isNotification) {
    if (classification.headerVersion !== version || transportMeta.method !== rpc.method) {
      return rpcError(rpc.id ?? null, -32020, "MCP header/body mismatch", {
        expectedProtocolVersion: version,
        expectedMethod: rpc.method
      });
    }
    if (rpc.method === "tools/call" && transportMeta.name !== rpc.params?.name) {
      return rpcError(rpc.id ?? null, -32020, "MCP header/body mismatch", {
        expectedName: rpc.params?.name ?? null
      });
    }
  }
  return null;
}

async function compareWindow(windowId, options) {
  const record = getWindow(windowId, options.now);
  if (!record) return null;
  const state = await buildState(options);
  const baseline = record.window.baseline.btcusdt_last_price;
  const current = state.market.last_price_usdt;
  return {
    window_id: windowId,
    boundary_utc: record.window.boundary_utc,
    phase: record.phase,
    observed_at_utc: state.observed_at_utc,
    baseline_btcusdt: baseline,
    current_btcusdt: current,
    current_vs_baseline_pct: Number((((current - baseline) / baseline) * 100).toFixed(4)),
    market_source: state.market.source,
    market_freshness: state.market.freshness,
    trading_authority: false
  };
}

export async function handleMcpRpc(body, { fetchImpl = fetch, now = new Date(), transportMeta = {} } = {}) {
  const rpc = parseRpc(body);
  if (!rpc) return { status: 400, body: rpcError(null, -32600, "Invalid Request") };
  const id = rpc.id ?? null;
  const classification = classifyEra(rpc, transportMeta);
  if (classification.error) return { status: 400, body: classification.error };
  const modern = classification.modern;

  if (modern) {
    const validationError = validateModernRequest(rpc, transportMeta, classification);
    if (validationError) return { status: 400, body: validationError };
    if (rpc.method === "initialize" || rpc.method === "ping") {
      return { status: 404, body: rpcError(id, -32601, "Method not found") };
    }
  }

  if (rpc.method.startsWith("notifications/")) return { status: 202, body: null };
  if (rpc.method === "ping") return { status: 200, body: rpcResult(id, {}) };
  if (rpc.method === "server/discover") {
    return {
      status: 200,
      body: rpcResult(id, completeResult({
        supportedVersions: MCP_SUPPORTED_PROTOCOL_VERSIONS,
        capabilities: SERVER_CAPABILITIES,
        instructions: SERVER_INSTRUCTIONS
      }, true, true))
    };
  }
  if (rpc.method === "initialize") {
    const requested = rpc.params?.protocolVersion;
    const protocolVersion = requested === "2025-03-26" ? "2025-03-26" : MCP_LEGACY_PROTOCOL_VERSION;
    return {
      status: 200,
      body: rpcResult(id, {
        protocolVersion,
        capabilities: SERVER_CAPABILITIES,
        serverInfo: SERVER_INFO,
        instructions: SERVER_INSTRUCTIONS
      })
    };
  }
  if (rpc.method === "tools/list") {
    return { status: 200, body: rpcResult(id, completeResult({ tools: MCP_TOOLS }, modern, modern)) };
  }
  if (rpc.method !== "tools/call") return { status: 404, body: rpcError(id, -32601, "Method not found") };

  const name = rpc.params?.name;
  const args = rpc.params?.arguments ?? {};
  if (typeof name !== "string" || !args || typeof args !== "object" || Array.isArray(args)) {
    return { status: 400, body: rpcError(id, -32602, "Invalid params") };
  }

  try {
    if (name === "bhrigu_get_bitcoin_research_state") {
      return { status: 200, body: rpcResult(id, toolResult(await buildState({ fetchImpl, now }), modern)) };
    }
    if (name === "bhrigu_list_temporal_windows") {
      return { status: 200, body: rpcResult(id, toolResult({ windows: listWindows(now) }, modern)) };
    }
    if (name === "bhrigu_get_temporal_window") {
      const windowId = parseWindowId(args);
      const record = windowId ? getWindow(windowId, now) : null;
      if (!record) return { status: 200, body: rpcResult(id, toolError("WINDOW_NOT_FOUND", "Unknown or missing window_id.", modern)) };
      return { status: 200, body: rpcResult(id, toolResult(record, modern)) };
    }
    if (name === "bhrigu_compare_window_to_reality") {
      const windowId = parseWindowId(args);
      const comparison = windowId ? await compareWindow(windowId, { fetchImpl, now }) : null;
      if (!comparison) return { status: 200, body: rpcResult(id, toolError("WINDOW_NOT_FOUND", "Unknown or missing window_id.", modern)) };
      return { status: 200, body: rpcResult(id, toolResult(comparison, modern)) };
    }
    return { status: 200, body: rpcResult(id, toolError("TOOL_NOT_FOUND", `Unknown tool: ${name}`, modern)) };
  } catch (error) {
    return { status: 200, body: rpcResult(id, toolError("PUBLIC_SOURCE_UNAVAILABLE", String(error.message || error), modern)) };
  }
}
