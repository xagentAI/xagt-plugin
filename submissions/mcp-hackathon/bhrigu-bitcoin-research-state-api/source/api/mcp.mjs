import { sendJson } from "../lib/http.mjs";
import { handleMcpRpc } from "../lib/mcp.mjs";

async function readBody(req) {
  if (req.body && typeof req.body === "object") return req.body;
  let raw = "";
  for await (const chunk of req) raw += chunk;
  return raw ? JSON.parse(raw) : null;
}

function headerValue(req, name) {
  const headers = req.headers;
  if (headers?.get) return headers.get(name);
  const value = headers?.[name.toLowerCase()] ?? headers?.[name];
  return Array.isArray(value) ? value[0] : value ?? null;
}

export default async function handler(req, res) {
  if (req.method !== "POST") return sendJson(res, 405, { error: "METHOD_NOT_ALLOWED", allowed: ["POST"] });
  try {
    const result = await handleMcpRpc(await readBody(req), {
      transportMeta: {
        requireHeaders: true,
        protocolVersion: headerValue(req, "MCP-Protocol-Version"),
        method: headerValue(req, "Mcp-Method"),
        name: headerValue(req, "Mcp-Name")
      }
    });
    if (result.status === 202) {
      res.statusCode = 202;
      return res.end();
    }
    sendJson(res, result.status, result.body, "no-store");
  } catch {
    sendJson(res, 400, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "Parse error" } });
  }
}
