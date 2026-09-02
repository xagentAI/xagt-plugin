import { createExecutionContext, env } from "cloudflare:test";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import worker from "../src/index";
import { REVIEW_KEY, mockOutbound, resetDatabase } from "./fixtures";

async function mcp(payload: unknown, authenticated = true): Promise<Response> {
  return worker.fetch(
    new Request("https://api.finfold.app/mcp", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        ...(authenticated ? { authorization: `Bearer ${REVIEW_KEY}` } : {}),
      },
      body: JSON.stringify(payload),
    }),
    env,
    createExecutionContext(),
  );
}

beforeEach(async () => {
  await resetDatabase();
  mockOutbound();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Streamable HTTP MCP", () => {
  it("negotiates initialize", async () => {
    const response = await mcp(
      { jsonrpc: "2.0", id: 1, method: "initialize", params: { protocolVersion: "2025-11-25", capabilities: {}, clientInfo: { name: "test", version: "1" } } },
      false,
    );
    expect(await response.json()).toMatchObject({
      jsonrpc: "2.0",
      id: 1,
      result: { protocolVersion: "2025-11-25", capabilities: { tools: { listChanged: false } } },
    });
  });

  it("returns 202 for initialized notification", async () => {
    const response = await mcp({ jsonrpc: "2.0", method: "notifications/initialized" }, false);
    expect(response.status).toBe(202);
    expect(await response.text()).toBe("");
  });

  it("lists the three scoped tools with mutation annotations", async () => {
    const response = await mcp({ jsonrpc: "2.0", id: "tools", method: "tools/list", params: {} });
    const body = (await response.json()) as Record<string, any>;
    expect(body.result.tools.map((tool: { name: string }) => tool.name)).toEqual([
      "finfold_create_growth_mission",
      "finfold_get_growth_mission",
      "finfold_record_growth_outcome",
    ]);
    expect(body.result.tools[0].annotations).toMatchObject({ readOnlyHint: false, idempotentHint: true });
    expect(body.result.tools[1].annotations).toMatchObject({ readOnlyHint: true });
  });

  it("creates a real mission through tools/call", async () => {
    const response = await mcp({
      jsonrpc: "2.0",
      id: 2,
      method: "tools/call",
      params: {
        name: "finfold_create_growth_mission",
        arguments: {
          sourceUrl: "https://acme.test/",
          objective: "leads",
          platform: "linkedin",
          locale: "en",
          idempotencyKey: "mcp-create-0001",
        },
      },
    });
    const body = (await response.json()) as Record<string, any>;
    expect(body.result.isError).toBe(false);
    expect(body.result.structuredContent.mission.id).toMatch(/^gm_[a-z0-9]{24}$/);
  });

  it("uses MCP tool error semantics for invalid arguments", async () => {
    const response = await mcp({
      jsonrpc: "2.0",
      id: 3,
      method: "tools/call",
      params: { name: "finfold_get_growth_mission", arguments: { missionId: "bad" } },
    });
    expect(await response.json()).toMatchObject({
      jsonrpc: "2.0",
      id: 3,
      result: { isError: true },
    });
  });

  it("returns JSON-RPC method-not-found for unknown methods", async () => {
    const response = await mcp({ jsonrpc: "2.0", id: 4, method: "resources/list" });
    expect(response.status).toBe(404);
    expect(await response.json()).toMatchObject({ error: { code: -32601 } });
  });
});
