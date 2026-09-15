import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FastifyInstance } from "fastify";
import { buildServer } from "../src/server.js";
import { resetGasOracleCache } from "../src/routes/gasCurrent.js";

function etherscanResponse(result: unknown) {
  return new Response(JSON.stringify({ status: "1", message: "OK", result }), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("GET /v1/gas/current", () => {
  let app: FastifyInstance;

  beforeEach(async () => {
    resetGasOracleCache();
    app = await buildServer();
  });

  afterEach(async () => {
    await app.close();
    vi.restoreAllMocks();
  });

  it("returns parsed gas price tiers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        etherscanResponse({
          LastBlock: "25901325",
          SafeGasPrice: "12.1",
          ProposeGasPrice: "14.3",
          FastGasPrice: "18.7",
        }),
      ),
    );

    const response = await app.inject({ method: "GET", url: "/v1/gas/current" });
    expect(response.statusCode).toBe(200);
    const body = response.json();
    expect(body).toMatchObject({
      network: "ethereum-mainnet",
      safeGwei: 12.1,
      standardGwei: 14.3,
      fastGwei: 18.7,
      dataSource: "etherscan",
    });
    expect(typeof body.asOf).toBe("string");
  });

  it("returns 502 when the upstream is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("boom", { status: 500 })));

    const response = await app.inject({ method: "GET", url: "/v1/gas/current" });
    expect(response.statusCode).toBe(502);
    expect(response.json().error.code).toBe("upstream_unavailable");
  });

  it("returns 429 when the upstream rate-limits", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("too many", { status: 429 })));

    const response = await app.inject({ method: "GET", url: "/v1/gas/current" });
    expect(response.statusCode).toBe(429);
    expect(response.json().error.code).toBe("upstream_rate_limited");
  });

  it("serves the cached value on a second call without a new upstream request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      etherscanResponse({ LastBlock: "1", SafeGasPrice: "1", ProposeGasPrice: "2", FastGasPrice: "3" }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await app.inject({ method: "GET", url: "/v1/gas/current" });
    await app.inject({ method: "GET", url: "/v1/gas/current" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
