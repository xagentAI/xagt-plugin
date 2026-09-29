import { afterEach, describe, expect, it, vi } from "vitest";

import { ASSOCIATION_COPY, STATUS_COPY, describeApiError, isTerminalStatus, publicApi } from "@/lib/public-api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("publicApi", () => {
  it("POSTs the create body to /v1/payment-intents and returns the resource", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ id: "pi_x" }, 201));
    vi.stubGlobal("fetch", fetchMock);
    const body = { chain: "base" as const, asset: "USDC" as const, amount: "1", recipient: "0x", expiresAt: "2026-01-01T00:00:00.000Z" };
    const result = await publicApi.createPaymentIntent(body);
    expect(result).toEqual({ ok: true, data: { id: "pi_x" } });
    expect(fetchMock).toHaveBeenCalledWith("/v1/payment-intents", expect.objectContaining({ method: "POST", body: JSON.stringify(body) }));
  });

  it("uses the public reconcile and evidence endpoints with an encoded id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    await publicApi.reconcilePaymentIntent("pi_a b");
    await publicApi.getEvidence("pi_a b", 50);
    await publicApi.getPaymentIntent("pi_a b");
    expect(fetchMock.mock.calls.map((call) => [call[0], (call[1] as RequestInit | undefined)?.method ?? "GET"])).toEqual([
      ["/v1/payment-intents/pi_a%20b/reconcile", "POST"],
      ["/v1/payment-intents/pi_a%20b/evidence?limit=50", "GET"],
      ["/v1/payment-intents/pi_a%20b", "GET"],
    ]);
  });

  it("maps the API error envelope to a typed error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ error: { code: "UPSTREAM_UNAVAILABLE", message: "down", retryable: true } }, 503)),
    );
    const result = await publicApi.reconcilePaymentIntent("pi_x");
    expect(result).toEqual({ ok: false, error: { code: "UPSTREAM_UNAVAILABLE", message: "down", retryable: true, status: 503 } });
  });

  it("treats unknown bodies and network failures safely", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 502 })));
    const bad = await publicApi.getPaymentIntent("pi_x");
    expect(bad.ok === false && bad.error.code).toBe("INTERNAL_ERROR");

    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const offline = await publicApi.getPaymentIntent("pi_x");
    expect(offline.ok === false && offline.error).toEqual({ code: "NETWORK_ERROR", message: "Could not reach Settle.", retryable: true, status: null });
  });
});

describe("copy tables", () => {
  it("covers all seven statuses with label, explanation and a non-colour glyph", () => {
    expect(Object.keys(STATUS_COPY).sort()).toEqual(["ambiguous", "detected", "expired", "overpaid", "paid", "partial", "pending"]);
    for (const copy of Object.values(STATUS_COPY)) {
      expect(copy.label.length).toBeGreaterThan(0);
      expect(copy.explanation.length).toBeGreaterThan(10);
      expect(copy.glyph.length).toBeGreaterThan(0);
    }
    expect(Object.keys(ASSOCIATION_COPY).sort()).toEqual(["candidate", "matched", "orphaned"]);
  });

  it("marks exactly paid/overpaid/expired/ambiguous as terminal", () => {
    expect(["paid", "overpaid", "expired", "ambiguous"].every((status) => isTerminalStatus(status as never))).toBe(true);
    expect(["pending", "detected", "partial"].some((status) => isTerminalStatus(status as never))).toBe(false);
  });

  it("frames every stable error code without leaking internals, and never as 'no payment found'", () => {
    for (const code of [
      "VALIDATION_ERROR",
      "INVALID_ADDRESS",
      "UNSUPPORTED_CHAIN",
      "UNSUPPORTED_ASSET",
      "INTENT_NOT_FOUND",
      "RATE_LIMITED",
      "UPSTREAM_UNAVAILABLE",
      "UPSTREAM_INVALID_RESPONSE",
      "INTERNAL_ERROR",
      "NETWORK_ERROR",
    ] as const) {
      const copy = describeApiError({ code, message: "server said: at Object.<anonymous> (/srv/app.js:1:1)", retryable: false, status: 500 });
      expect(copy.title.length).toBeGreaterThan(0);
      // An upstream failure must never read as a payment result.
      expect(copy.title.toLowerCase()).not.toContain("no payment");
      expect(copy.detail).not.toMatch(/^no payment found/i);
      if (code !== "VALIDATION_ERROR" && code !== "INVALID_ADDRESS") {
        expect(copy.detail).not.toContain("/srv/app.js");
      }
    }
    expect(describeApiError({ code: "UPSTREAM_UNAVAILABLE", message: "", retryable: true, status: 503 }).detail).toMatch(/last known payment state/i);
  });
});
