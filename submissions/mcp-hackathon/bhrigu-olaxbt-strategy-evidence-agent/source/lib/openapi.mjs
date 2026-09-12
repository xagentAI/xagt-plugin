import { runtimeCommit } from "./runtime.mjs";

export function openapiPayload() {
  return {
    openapi: "3.1.0",
    info: {
      title: "BHRIGU Strategy Evidence Agent",
      version: "0.2.0",
      description: "Read-only evidence interpretation around the current OlaXBT strategy signal. OlaXBT remains strategy + signal authority; BHRIGU creates no second signal and executes no trades."
    },
    servers: [{ url: "/" }],
    paths: {
      "/v1/state": { get: { summary: "Live Bitcoin research state" } },
      "/v1/strategy-evidence": { post: { summary: "Read-only OlaXBT strategy evidence assessment; no new trading signal" } },
      "/v1/windows": { get: { summary: "List precommitted temporal windows" } },
      "/v1/windows/{id}": { get: { summary: "Get one window and durable evidence" } },
      "/mcp": { post: { summary: "Stateless Streamable HTTP MCP JSON-RPC endpoint" } },
      "/health": { get: { summary: "Health and exact commit binding" } }
    },
    "x-bhrigu": {
      commit: runtimeCommit(),
      boundary: "RESEARCH_STATE_NOT_TRADE",
      trading: false,
      wallet: false,
      payment: false,
      olaxbt_strategy_evidence: "read_only"
    }
  };
}
