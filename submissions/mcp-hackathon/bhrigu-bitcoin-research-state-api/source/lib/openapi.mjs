import { runtimeCommit } from "./runtime.mjs";

export function openapiPayload() {
  return {
    openapi: "3.1.0",
    info: {
      title: "BHRIGU Bitcoin Temporal Evidence API",
      version: "0.2.0",
      description: "Read-only Bitcoin state and precommitted temporal evidence for AI agents."
    },
    servers: [{ url: "https://bhrigu-bitcoin-research-state-api.vercel.app" }],
    paths: {
      "/v1/state": { get: { summary: "Live Bitcoin research state" } },
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
      payment: false
    }
  };
}
