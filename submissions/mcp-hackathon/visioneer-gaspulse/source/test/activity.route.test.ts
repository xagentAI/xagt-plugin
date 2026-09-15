import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server.js";

// Distinct addresses per test: the route caches Etherscan responses per address for 60s,
// so reusing one address across tests would return stale cached data instead of the mock.
const ADDR_MALFORMED_WINDOW = `0x${"5".repeat(40)}`;
const ADDR_EMPTY = `0x${"1".repeat(40)}`;
const ADDR_ACTIVE = `0x${"2".repeat(40)}`;
const ADDR_UNAVAILABLE = `0x${"3".repeat(40)}`;
const ADDR_RATE_LIMITED = `0x${"4".repeat(40)}`;

function etherscanResponse(result: unknown) {
  return new Response(JSON.stringify({ status: "1", message: "OK", result }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("GET /v1/address/:address/activity", () => {
  let app: FastifyInstance;

  beforeEach(async () => {
    app = await buildServer();
  });

  afterEach(async () => {
    await app.close();
    vi.restoreAllMocks();
  });

  it("rejects a malformed address with 400", async () => {
    const response = await app.inject({ method: "GET", url: "/v1/address/not-an-address/activity" });
    expect(response.statusCode).toBe(400);
    expect(response.json().error.code).toBe("invalid_address");
  });

  it("rejects an out-of-range windowDays with 400", async () => {
    const response = await app.inject({
      method: "GET",
      url: `/v1/address/${ADDR_MALFORMED_WINDOW}/activity?windowDays=999`,
    });
    expect(response.statusCode).toBe(400);
    expect(response.json().error.code).toBe("invalid_window");
  });

  it("returns a zeroed response for an address with no transactions", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(etherscanResponse([])));

    const response = await app.inject({ method: "GET", url: `/v1/address/${ADDR_EMPTY}/activity` });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body.txCount).toBe(0);
    expect(body.activityScore).toEqual({ value: 0, recency: 0, frequency: 0, consistency: 0 });
    expect(body.gasTrend.direction).toBe("insufficient_data");
  });

  it("computes activity from returned transactions", async () => {
    const now = Math.floor(Date.now() / 1000);
    const sampleTx = {
      hash: "0xabc",
      timeStamp: String(now - 86_400),
      gas: "21000",
      gasPrice: "10000000000",
      gasUsed: "21000",
      isError: "0",
    };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(etherscanResponse([sampleTx])));

    const response = await app.inject({ method: "GET", url: `/v1/address/${ADDR_ACTIVE}/activity` });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body.txCount).toBe(1);
    expect(body.dataSource).toBe("etherscan");
    expect(body.address).toBe(ADDR_ACTIVE.toLowerCase());
  });

  it("returns 502 when the upstream is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("boom", { status: 500 })));

    const response = await app.inject({ method: "GET", url: `/v1/address/${ADDR_UNAVAILABLE}/activity` });
    expect(response.statusCode).toBe(502);
    expect(response.json().error.code).toBe("upstream_unavailable");
  });

  it("returns 429 when the upstream rate-limits", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("too many", { status: 429 })));

    const response = await app.inject({ method: "GET", url: `/v1/address/${ADDR_RATE_LIMITED}/activity` });
    expect(response.statusCode).toBe(429);
    expect(response.json().error.code).toBe("upstream_rate_limited");
  });
});
