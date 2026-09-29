import assert from "node:assert/strict";
import {
  handleMcpRpc,
  MCP_TOOLS,
  MCP_MODERN_PROTOCOL_VERSION,
  MCP_SUPPORTED_PROTOCOL_VERSIONS
} from "../lib/mcp.mjs";

let checks = 0;
const eq = (actual, expected, message) => { assert.equal(actual, expected, message); checks += 1; };
const deep = (actual, expected, message) => { assert.deepEqual(actual, expected, message); checks += 1; };

const fakeFetch = async (url) => {
  if (String(url).includes("data-api.binance.vision")) {
    return new Response(JSON.stringify({
      lastPrice: "79000.00", priceChangePercent: "1.25", highPrice: "80000.00",
      lowPrice: "77000.00", volume: "12345.67", closeTime: Date.parse("2026-09-16T12:00:00Z")
    }), { status: 200 });
  }
  if (String(url).includes("mempool.space")) return new Response("967000", { status: 200 });
  throw new Error("UNEXPECTED_URL");
};
const now = new Date("2026-09-16T12:00:30Z");
const modernMeta = {
  "io.modelcontextprotocol/protocolVersion": MCP_MODERN_PROTOCOL_VERSION,
  "io.modelcontextprotocol/clientCapabilities": {},
  "io.modelcontextprotocol/clientInfo": { name: "bhrigu-test", version: "1.0.0" }
};
const modernTransport = (method, name = null) => ({ requireHeaders: true, protocolVersion: MCP_MODERN_PROTOCOL_VERSION, method, name });

const init = await handleMcpRpc({ jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25" } }, { fetchImpl: fakeFetch, now });
eq(init.status, 200);
eq(init.body.result.protocolVersion, "2025-11-25");
eq(init.body.result.serverInfo.version, "0.2.0");
eq(init.body.result.resultType, undefined);

const legacyList = await handleMcpRpc({ jsonrpc: "2.0", id: 2, method: "tools/list" }, { fetchImpl: fakeFetch, now });
eq(legacyList.status, 200);
eq(legacyList.body.result.tools.length, 4);
eq(legacyList.body.result.ttlMs, undefined);

const discover = await handleMcpRpc({ jsonrpc: "2.0", id: 3, method: "server/discover", params: { _meta: modernMeta } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("server/discover") });
eq(discover.status, 200);
eq(discover.body.result.resultType, "complete");
eq(discover.body.result.ttlMs, 300000);
eq(discover.body.result.cacheScope, "public");
deep(discover.body.result.supportedVersions, MCP_SUPPORTED_PROTOCOL_VERSIONS);
eq(discover.body.result.serverInfo, undefined);
eq(discover.body.result._meta["io.modelcontextprotocol/serverInfo"].name, "bhrigu-bitcoin-research-state-api");

const list = await handleMcpRpc({ jsonrpc: "2.0", id: 4, method: "tools/list", params: { _meta: modernMeta } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/list") });
eq(list.status, 200);
eq(list.body.result.resultType, "complete");
eq(list.body.result.tools.length, 4);
deep(list.body.result.tools.map((t) => t.name), MCP_TOOLS.map((t) => t.name));
eq(list.body.result.tools.every((t) => t.annotations.readOnlyHint === true), true);
eq(list.body.result.ttlMs, 300000);
eq(list.body.result.cacheScope, "public");

const noClientInfo = await handleMcpRpc({ jsonrpc: "2.0", id: 41, method: "tools/list", params: { _meta: {
  "io.modelcontextprotocol/protocolVersion": MCP_MODERN_PROTOCOL_VERSION,
  "io.modelcontextprotocol/clientCapabilities": {}
} } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/list") });
eq(noClientInfo.status, 200);

const malformedClientInfo = await handleMcpRpc({ jsonrpc: "2.0", id: 42, method: "tools/list", params: { _meta: {
  ...modernMeta, "io.modelcontextprotocol/clientInfo": { name: "missing-version" }
} } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/list") });
eq(malformedClientInfo.status, 400);
eq(malformedClientInfo.body.error.code, -32602);

const windowResult = await handleMcpRpc({ jsonrpc: "2.0", id: 5, method: "tools/call", params: {
  name: "bhrigu_get_temporal_window", arguments: { window_id: "SEP_10_2026" }, _meta: modernMeta
} }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/call", "bhrigu_get_temporal_window") });
eq(windowResult.status, 200);
eq(windowResult.body.result.resultType, "complete");
eq(windowResult.body.result.isError, false);
eq(windowResult.body.result.structuredContent.window.id, "SEP_10_2026");
eq(windowResult.body.result.structuredContent.evidence.length, 1);

const compare = await handleMcpRpc({ jsonrpc: "2.0", id: 6, method: "tools/call", params: {
  name: "bhrigu_compare_window_to_reality", arguments: { window_id: "SEP_17_2026" }, _meta: modernMeta
} }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/call", "bhrigu_compare_window_to_reality") });
eq(compare.body.result.isError, false);
eq(compare.body.result.resultType, "complete");
eq(compare.body.result.structuredContent.current_btcusdt, 79000);
eq(compare.body.result.structuredContent.baseline_btcusdt, 78348.09);
eq(compare.body.result.structuredContent.trading_authority, false);

const headerMismatch = await handleMcpRpc({ jsonrpc: "2.0", id: 7, method: "tools/list", params: { _meta: modernMeta } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/call") });
eq(headerMismatch.status, 400);
eq(headerMismatch.body.error.code, -32020);

const missingCaps = await handleMcpRpc({ jsonrpc: "2.0", id: 8, method: "server/discover", params: { _meta: {
  "io.modelcontextprotocol/protocolVersion": MCP_MODERN_PROTOCOL_VERSION
} } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("server/discover") });
eq(missingCaps.status, 400);
eq(missingCaps.body.error.code, -32602);

const missingVersion = await handleMcpRpc({ jsonrpc: "2.0", id: 81, method: "server/discover", params: { _meta: {
  "io.modelcontextprotocol/clientCapabilities": {}
} } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("server/discover") });
eq(missingVersion.status, 400);
eq(missingVersion.body.error.code, -32602);

const unsupported = await handleMcpRpc({ jsonrpc: "2.0", id: 9, method: "server/discover", params: { _meta: {
  ...modernMeta, "io.modelcontextprotocol/protocolVersion": "2099-01-01"
} } }, { fetchImpl: fakeFetch, now, transportMeta: { ...modernTransport("server/discover"), protocolVersion: "2099-01-01" } });
eq(unsupported.status, 400);
eq(unsupported.body.error.code, -32022);
eq(unsupported.body.error.data.requested, "2099-01-01");
deep(unsupported.body.error.data.supported, MCP_SUPPORTED_PROTOCOL_VERSIONS);

const unsupportedOrdinary = await handleMcpRpc({ jsonrpc: "2.0", id: 10, method: "tools/list", params: { _meta: {
  ...modernMeta, "io.modelcontextprotocol/protocolVersion": "2099-01-01"
} } }, { fetchImpl: fakeFetch, now, transportMeta: { ...modernTransport("tools/list"), protocolVersion: "2099-01-01" } });
eq(unsupportedOrdinary.status, 400);
eq(unsupportedOrdinary.body.error.code, -32022);

const unsupportedHeaderOnly = await handleMcpRpc({ jsonrpc: "2.0", id: 101, method: "tools/list" }, { fetchImpl: fakeFetch, now,
  transportMeta: { requireHeaders: true, protocolVersion: "2099-01-01", method: "tools/list", name: null } });
eq(unsupportedHeaderOnly.status, 400);
eq(unsupportedHeaderOnly.body.error.code, -32022);

const modernPing = await handleMcpRpc({ jsonrpc: "2.0", id: 102, method: "ping", params: { _meta: modernMeta } }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("ping") });
eq(modernPing.status, 404);
eq(modernPing.body.error.code, -32601);

const modernNotification = await handleMcpRpc({ jsonrpc: "2.0", method: "notifications/example", params: { _meta: modernMeta } }, { fetchImpl: fakeFetch, now, transportMeta: { requireHeaders: true } });
eq(modernNotification.status, 202);
eq(modernNotification.body, null);

const bad = await handleMcpRpc({ jsonrpc: "2.0", id: 11, method: "tools/call", params: {
  name: "bhrigu_get_temporal_window", arguments: { window_id: "NOPE" }, _meta: modernMeta
} }, { fetchImpl: fakeFetch, now, transportMeta: modernTransport("tools/call", "bhrigu_get_temporal_window") });
eq(bad.body.result.isError, true);
eq(bad.body.result.structuredContent.error.code, "WINDOW_NOT_FOUND");

const invalid = await handleMcpRpc({ hello: "world" });
eq(invalid.status, 400);
eq(invalid.body.error.code, -32600);

console.log(JSON.stringify({ schema: "bhrigu_mcp_tests_v0_4", status: "PASS", checks }));
