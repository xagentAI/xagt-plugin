#!/usr/bin/env node
/**
 * Minimal MCP stdio server (JSON-RPC 2.0, newline-delimited).
 * Tools: list_venues, get_venue, resolve_session.
 */
import { createInterface } from "node:readline";
import { daySchedule, listVenues, resolveSession, venueDescriptor } from "./calendar.js";

const PROTOCOL_VERSION = "2024-11-05";

function ok(id, result) {
  return { jsonrpc: "2.0", id, result };
}

function fail(id, code, message) {
  return { jsonrpc: "2.0", id, error: { code, message } };
}

function toolText(id, value) {
  return ok(id, { content: [{ type: "text", text: JSON.stringify(value, null, 2) }] });
}

function handle(message) {
  const { id, method, params } = message;
  if (method === "initialize") {
    return ok(id, {
      protocolVersion: PROTOCOL_VERSION,
      serverInfo: { name: "venueclock", version: "1.0.0" },
      capabilities: { tools: {} }
    });
  }
  if (method === "notifications/initialized" || method === "notifications/cancelled") {
    return null;
  }
  if (method === "ping") return ok(id, {});
  if (method === "tools/list") {
    return ok(id, {
      tools: [
        {
          name: "list_venues",
          description: "List supported market venues (MIC, timezone).",
          inputSchema: { type: "object", properties: {}, additionalProperties: false }
        },
        {
          name: "get_venue",
          description: "Return session rules, timezone, and 2026 holidays for a venue.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            required: ["venue"],
            properties: { venue: { type: "string" } }
          }
        },
        {
          name: "resolve_session",
          description: "Return session state for a venue at an instant, or a full day schedule when date is set.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            required: ["venue"],
            properties: {
              venue: { type: "string" },
              at: { type: "string" },
              date: { type: "string" }
            }
          }
        }
      ]
    });
  }
  if (method === "tools/call") {
    const name = params?.name;
    const args = params?.arguments ?? {};
    if (name === "list_venues") return toolText(id, { venues: listVenues() });
    if (name === "get_venue") {
      const descriptor = venueDescriptor(args.venue);
      if (!descriptor) return toolText(id, { error: "unknown_venue", message: `Unknown venue: ${args.venue}` });
      return toolText(id, descriptor);
    }
    if (name === "resolve_session") {
      if (args.date && !args.at) return toolText(id, daySchedule(args.venue, args.date));
      return toolText(id, resolveSession(args.venue, args.at || new Date()));
    }
    return fail(id, -32601, `Unknown tool: ${name}`);
  }
  if (id === undefined) return null;
  return fail(id, -32601, `Unknown method: ${method}`);
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
rl.on("line", (line) => {
  if (!line.trim()) return;
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    process.stdout.write(`${JSON.stringify({ jsonrpc: "2.0", error: { code: -32700, message: "parse error" } })}\n`);
    return;
  }
  const response = handle(message);
  if (response) process.stdout.write(`${JSON.stringify(response)}\n`);
});
