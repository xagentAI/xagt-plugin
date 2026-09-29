import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors";
import { REQUEST_ID_HEADER, apiRoute, jsonResponse, resolveRequestId } from "@/lib/http";

const REQUEST_ID_PATTERN = /^req_[A-Za-z0-9_-]{22}$/;

describe("resolveRequestId", () => {
  it("generates a fresh id when none is supplied", () => {
    expect(resolveRequestId(new Headers())).toMatch(REQUEST_ID_PATTERN);
  });

  it("honours a safe client-supplied id", () => {
    const headers = new Headers({ [REQUEST_ID_HEADER]: "agent-run-42_abc" });
    expect(resolveRequestId(headers)).toBe("agent-run-42_abc");
  });

  it("replaces unsafe or oversized client ids", () => {
    expect(resolveRequestId(new Headers({ [REQUEST_ID_HEADER]: "short" }))).toMatch(
      REQUEST_ID_PATTERN,
    );
    expect(resolveRequestId(new Headers({ [REQUEST_ID_HEADER]: "has spaces and ;" }))).toMatch(
      REQUEST_ID_PATTERN,
    );
    expect(resolveRequestId(new Headers({ [REQUEST_ID_HEADER]: "x".repeat(65) }))).toMatch(
      REQUEST_ID_PATTERN,
    );
  });
});

describe("jsonResponse", () => {
  it("sets JSON content type, request id and no-store caching", async () => {
    const response = jsonResponse({ ok: true }, { requestId: "req_test", status: 201 });
    expect(response.status).toBe(201);
    expect(response.headers.get("content-type")).toMatch(/^application\/json/);
    expect(response.headers.get(REQUEST_ID_HEADER)).toBe("req_test");
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual({ ok: true });
  });
});

describe("apiRoute", () => {
  it("passes a request context and stamps X-Request-Id on the handler's response", async () => {
    const handler = apiRoute("/echo", ({ requestId, request }) =>
      jsonResponse({ requestId, method: request.method }, { requestId }),
    );
    const response = await handler(
      new Request("http://localhost/echo", { headers: { [REQUEST_ID_HEADER]: "req_supplied_1" } }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get(REQUEST_ID_HEADER)).toBe("req_supplied_1");
    await expect(response.json()).resolves.toEqual({ requestId: "req_supplied_1", method: "GET" });
  });

  it("stamps X-Request-Id even when the handler builds a bare Response", async () => {
    const handler = apiRoute("/bare", () => new Response("ok"));
    const response = await handler(new Request("http://localhost/bare"));
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(REQUEST_ID_PATTERN);
  });

  it("maps AppError to its status and public envelope", async () => {
    const handler = apiRoute("/missing", () => {
      throw new AppError("INTENT_NOT_FOUND", "Payment intent not found");
    });
    const response = await handler(new Request("http://localhost/missing"));
    expect(response.status).toBe(404);
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(REQUEST_ID_PATTERN);
    await expect(response.json()).resolves.toEqual({
      error: { code: "INTENT_NOT_FOUND", message: "Payment intent not found", retryable: false },
    });
  });

  it("maps unknown errors to a generic INTERNAL_ERROR envelope", async () => {
    const handler = apiRoute("/boom", () => {
      throw new Error("pg: connection refused at 10.0.0.1");
    });
    const response = await handler(new Request("http://localhost/boom"));
    expect(response.status).toBe(500);
    const body = (await response.json()) as { error: { message: string } };
    expect(body).toEqual({
      error: { code: "INTERNAL_ERROR", message: "Unexpected internal error", retryable: false },
    });
    expect(body.error.message).not.toContain("10.0.0.1");
  });

  it("passes extra handler arguments through", async () => {
    const handler = apiRoute(
      "/items/[id]",
      async ({ requestId }, context: { params: Promise<{ id: string }> }) => {
        const { id } = await context.params;
        return jsonResponse({ id }, { requestId });
      },
    );
    const response = await handler(new Request("http://localhost/items/abc"), {
      params: Promise.resolve({ id: "abc" }),
    });
    await expect(response.json()).resolves.toEqual({ id: "abc" });
  });
});
