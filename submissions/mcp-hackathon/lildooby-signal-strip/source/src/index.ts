/**
 * Signal & Strip MCP server — HTTP entrypoint.
 *
 * Exposes the MCP server over Streamable HTTP at POST /mcp in stateless mode
 * (no session tracking; a fresh server instance is created per request).
 *
 * NOTE: This scaffold binds to localhost for local development. Meta Muse
 * runs in Meta's cloud, so a Muse custom connector can only reach this
 * server once it is deployed to a public HTTPS endpoint. Do NOT expose this
 * dev scaffold publicly without adding authentication, rate limiting, and a
 * real inventory/booking backend (see README).
 */

import cors from "cors";
import dotenv from "dotenv";
import express from "express";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { createSignalStripServer } from "./server.js";

dotenv.config();

const PORT = Number(process.env.PORT ?? 3000);
const HOST = process.env.HOST ?? "127.0.0.1";
const ALLOWED_HOSTS = (process.env.ALLOWED_HOSTS ?? "")
  .split(",")
  .map((h) => h.trim())
  .filter(Boolean);

// X-Agent hackathon deployment binding. Set DEPLOY_COMMIT to the exact
// 40-char git SHA of the deployed source at deploy time. XAGENT_SLUG must
// match the submission directory slug: submissions/mcp-hackathon/<slug>/.
const DEPLOY_COMMIT = process.env.DEPLOY_COMMIT?.trim() || "unpinned-local";
const XAGENT_SLUG = process.env.XAGENT_SLUG?.trim() || "lildooby-signal-strip";

const app = express();
app.use(cors());
app.use(express.json({ limit: "1mb" }));

app.get("/", (_req, res) => {
  res.json({
    name: "signal-strip",
    version: "0.1.0",
    description:
      "MCP server for Signal & Strip — the ad network for the agent economy.",
    mcp_endpoint: "POST /mcp (Streamable HTTP, stateless)",
    health: "GET /health",
    stub_notice:
      "Scaffold: static inventory, local-JSON booking intents, placeholder treasury wallet. See README before any public deployment.",
  });
});

app.get("/health", (_req, res) => {
  res.json({ status: "ok", commit: DEPLOY_COMMIT });
});

// X-Agent hackathon deployment proof endpoint (required by submission gates).
app.get("/.well-known/xagent-verification.json", (_req, res) => {
  res.json({ schemaVersion: 1, slug: XAGENT_SLUG, commit: DEPLOY_COMMIT });
});

app.post("/mcp", async (req, res) => {
  try {
    const server = createSignalStripServer();
    const transport = new StreamableHTTPServerTransport({
      sessionIdGenerator: undefined, // stateless mode
      allowedHosts: ALLOWED_HOSTS.length > 0 ? ALLOWED_HOSTS : undefined,
      enableDnsRebindingProtection: ALLOWED_HOSTS.length > 0,
    });
    await server.connect(transport);
    await transport.handleRequest(req, res, req.body);
  } catch (error) {
    console.error("Error handling MCP request:", error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: { code: -32603, message: "Internal server error" },
        id: null,
      });
    }
  }
});

// Stateless mode has no server-initiated streams; reject GET/DELETE on /mcp.
app.get("/mcp", (_req, res) => {
  res.status(405).json({
    error:
      "Method not allowed. This server runs stateless Streamable HTTP: use POST /mcp.",
  });
});
app.delete("/mcp", (_req, res) => {
  res.status(405).json({
    error:
      "Method not allowed. This server runs stateless Streamable HTTP: use POST /mcp.",
  });
});

app.listen(PORT, HOST, () => {
  console.log(`Signal & Strip MCP server listening on http://${HOST}:${PORT}`);
  console.log(`MCP endpoint: POST http://127.0.0.1:${PORT}/mcp`);
  if (process.env.SIGNAL_STRIP_TREASURY_WALLET?.trim()) {
    console.log("Treasury wallet: configured (from env)");
  } else {
    console.log(
      "Treasury wallet: NOT CONFIGURED (STUB) — set SIGNAL_STRIP_TREASURY_WALLET"
    );
  }
});
