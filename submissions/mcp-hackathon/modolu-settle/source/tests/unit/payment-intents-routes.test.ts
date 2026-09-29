import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Container } from "@/server/container";
import { GET as GET_EVIDENCE } from "@/app/v1/payment-intents/[id]/evidence/route";
import { POST as POST_RECONCILE } from "@/app/v1/payment-intents/[id]/reconcile/route";
import { GET } from "@/app/v1/payment-intents/[id]/route";
import { POST } from "@/app/v1/payment-intents/route";
import { AppError } from "@/lib/errors";
import { REQUEST_ID_HEADER } from "@/lib/http";
import { newPaymentIntentId } from "@/lib/ids";
import { createPaymentIntent } from "@/services/create-payment-intent";
import { getPaymentEvidence } from "@/services/get-payment-evidence";
import { getPaymentIntent } from "@/services/get-payment-intent";
import { reconcilePaymentIntent } from "@/services/reconcile-payment-intent";

import { FakeChainProvider, InMemoryPaymentRepository } from "../service/fakes";

// Route tests replace the composition root with services wired to in-memory
// fakes; the HTTP layer and the real services are exercised end to end.
const state: { container: Container } = { container: undefined as unknown as Container };
vi.mock("@/server/container", () => ({ getContainer: () => state.container }));

const RECIPIENT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913";
const PAYER = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045";

function wire(chainProvider: FakeChainProvider): InMemoryPaymentRepository {
  const paymentRepository = new InMemoryPaymentRepository();
  state.container = {
    createPaymentIntent: (input) => createPaymentIntent(input, { chainProvider, paymentRepository }),
    getPaymentIntent: (id) => getPaymentIntent(id, { paymentRepository }),
    reconcilePaymentIntent: (id, requestId) =>
      reconcilePaymentIntent(id, { chainProvider, paymentRepository, requestId }),
    getPaymentEvidence: (id, options) => getPaymentEvidence(id, options, { paymentRepository }),
  };
  return paymentRepository;
}

function post(body: unknown, headers: Record<string, string> = {}): Promise<Response> {
  return POST(
    new Request("http://localhost/v1/payment-intents", {
      method: "POST",
      headers: { "content-type": "application/json", ...headers },
      body: typeof body === "string" ? body : JSON.stringify(body),
    }),
  );
}

function get(id: string): Promise<Response> {
  return GET(new Request(`http://localhost/v1/payment-intents/${id}`), { params: Promise.resolve({ id }) });
}

function reconcile(id: string): Promise<Response> {
  return POST_RECONCILE(new Request(`http://localhost/v1/payment-intents/${id}/reconcile`, { method: "POST" }), {
    params: Promise.resolve({ id }),
  });
}

function evidence(id: string, query = ""): Promise<Response> {
  return GET_EVIDENCE(new Request(`http://localhost/v1/payment-intents/${id}/evidence${query}`), {
    params: Promise.resolve({ id }),
  });
}

const expiresAt = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString();
const validBody = {
  externalReference: "INV-204",
  chain: "base",
  asset: "USDC",
  amount: "850.00",
  recipient: RECIPIENT,
  payer: PAYER,
  expiresAt,
  requiredConfirmations: 3,
};

describe("POST /v1/payment-intents", () => {
  beforeEach(() => {
    wire(new FakeChainProvider({ latestBlock: 35_000_000n }));
  });

  it("creates an intent and returns 201 with the public representation", async () => {
    const response = await post(validBody);
    expect(response.status).toBe(201);
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(/^req_/);

    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({
      id: expect.stringMatching(/^pi_[A-Za-z0-9_-]{32}$/) as string,
      status: "pending",
      externalReference: "INV-204",
      chain: "base",
      asset: "USDC",
      expectedAmount: "850.00",
      receivedAmount: "0.00",
      remainingAmount: "850.00",
      recipient: RECIPIENT,
      payer: PAYER,
      requiredConfirmations: 3,
      matchConfidence: "none",
      paidAt: null,
      createdAt: expect.stringMatching(/Z$/) as string,
      expiresAt,
    });
    expect(body).not.toHaveProperty("startBlock");
    expect(body).not.toHaveProperty("accountId");
  });

  it("persists startBlock = latest block + 1 and defaults payer/confirmations", async () => {
    const repository = wire(new FakeChainProvider({ latestBlock: 41_999_999n }));
    const response = await post({ chain: "base", asset: "USDC", amount: "25", recipient: RECIPIENT, expiresAt });
    expect(response.status).toBe(201);
    const { id, payer, requiredConfirmations, expectedAmount } = (await response.json()) as Record<string, unknown>;
    expect(payer).toBeNull();
    expect(requiredConfirmations).toBe(3);
    expect(expectedAmount).toBe("25.00");
    expect(repository.intents.get(id as string)?.startBlock).toBe(42_000_000n);
  });

  it.each([
    ["unknown field", { ...validBody, chainId: 8453 }, 400, "VALIDATION_ERROR"],
    ["bad amount", { ...validBody, amount: "1e3" }, 400, "VALIDATION_ERROR"],
    ["past expiry", { ...validBody, expiresAt: "2020-01-01T00:00:00Z" }, 400, "VALIDATION_ERROR"],
    ["other chain", { ...validBody, chain: "ethereum" }, 400, "UNSUPPORTED_CHAIN"],
    ["other asset", { ...validBody, asset: "USDT" }, 400, "UNSUPPORTED_ASSET"],
    ["bad recipient", { ...validBody, recipient: "0xRecipient" }, 400, "INVALID_ADDRESS"],
    ["malformed JSON", "{not json", 400, "VALIDATION_ERROR"],
  ])("returns %s → %d %s", async (_label, body, status, code) => {
    const repository = wire(new FakeChainProvider({ latestBlock: 1n }));
    const response = await post(body);
    expect(response.status).toBe(status);
    const envelope = (await response.json()) as { error: { code: string; retryable: boolean } };
    expect(envelope.error.code).toBe(code);
    expect(envelope.error.retryable).toBe(false);
    expect(repository.intents.size).toBe(0);
  });

  it("rejects a wrong content type", async () => {
    const response = await post(validBody, { "content-type": "text/plain" });
    expect(response.status).toBe(400);
  });

  it("returns 503 UPSTREAM_UNAVAILABLE and creates nothing when the provider is down", async () => {
    const repository = wire(
      new FakeChainProvider({
        error: new AppError("UPSTREAM_UNAVAILABLE", "Blockchain provider is temporarily unavailable"),
      }),
    );
    const response = await post(validBody);
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: "UPSTREAM_UNAVAILABLE",
        message: "Blockchain provider is temporarily unavailable",
        retryable: true,
      },
    });
    expect(repository.intents.size).toBe(0);
  });
});

describe("GET /v1/payment-intents/:id", () => {
  it("returns the persisted intent with 200", async () => {
    wire(new FakeChainProvider({ latestBlock: 10n }));
    const created = (await (await post(validBody)).json()) as { id: string };

    const response = await get(created.id);
    expect(response.status).toBe(200);
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(/^req_/);
    await expect(response.json()).resolves.toEqual(created);
  });

  it("returns 404 INTENT_NOT_FOUND for a well-formed unknown ID", async () => {
    wire(new FakeChainProvider({ latestBlock: 10n }));
    const response = await get(newPaymentIntentId());
    expect(response.status).toBe(404);
    await expect(response.json()).resolves.toEqual({
      error: { code: "INTENT_NOT_FOUND", message: "Payment intent not found", retryable: false },
    });
  });

  it("returns 400 VALIDATION_ERROR for a malformed ID", async () => {
    wire(new FakeChainProvider({ latestBlock: 10n }));
    const response = await get("not-an-id");
    expect(response.status).toBe(400);
    const envelope = (await response.json()) as { error: { code: string } };
    expect(envelope.error.code).toBe("VALIDATION_ERROR");
  });
});

describe("POST /v1/payment-intents/:id/reconcile", () => {
  it("returns 200 with the reconciled intent at top level, X-Request-Id and no-store", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    const repository = wire(chainProvider);
    const created = (await (await post({ ...validBody, amount: "25.00" })).json()) as { id: string };
    expect(repository.intents.get(created.id)?.startBlock).toBe(101n);

    chainProvider.state.latestBlock = 150n;
    chainProvider.state.transfers = [
      {
        txHash: `0x${"e".repeat(64)}`,
        logIndex: 3,
        blockNumber: 120n,
        blockHash: `0x${"f".repeat(64)}`,
        from: PAYER.toLowerCase(),
        to: RECIPIENT.toLowerCase(),
        amountUnits: 25_000_000n,
      },
    ];
    chainProvider.state.timestamps = new Map([[120n, new Date("2026-09-17T22:30:00.000Z")]]);

    const response = await reconcile(created.id);
    expect(response.status).toBe(200);
    expect(response.headers.get(REQUEST_ID_HEADER)).toMatch(/^req_/);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toEqual({
      id: created.id,
      status: "paid",
      externalReference: "INV-204",
      chain: "base",
      asset: "USDC",
      expectedAmount: "25.00",
      receivedAmount: "25.00",
      remainingAmount: "0.00",
      recipient: RECIPIENT,
      payer: PAYER,
      requiredConfirmations: 3,
      matchConfidence: "exact_payer",
      paidAt: "2026-09-17T22:30:00.000Z",
      createdAt: expect.stringMatching(/Z$/) as string,
      expiresAt,
    });
    await expect((await get(created.id)).json()).resolves.toEqual(body);
  });

  it("returns pending with no evidence when nothing matched", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    wire(chainProvider);
    const created = (await (await post(validBody)).json()) as { id: string };
    const body = (await (await reconcile(created.id)).json()) as Record<string, unknown>;
    expect(body).toMatchObject({ status: "pending", receivedAmount: "0.00", matchConfidence: "none", paidAt: null });
  });

  it("returns 503 UPSTREAM_UNAVAILABLE when the provider fails and leaves the intent unchanged", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    wire(chainProvider);
    const created = (await (await post(validBody)).json()) as Record<string, unknown>;
    chainProvider.state.failLatestBlock = new AppError("UPSTREAM_UNAVAILABLE", "Blockchain provider is temporarily unavailable");
    const response = await reconcile(created["id"] as string);
    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: { code: "UPSTREAM_UNAVAILABLE", message: "Blockchain provider is temporarily unavailable", retryable: true },
    });
    await expect((await get(created["id"] as string)).json()).resolves.toEqual(created);
  });

  it("returns 404 for an unknown intent and 400 for a malformed ID", async () => {
    wire(new FakeChainProvider({ latestBlock: 1n, transfers: [] }));
    expect((await reconcile(newPaymentIntentId())).status).toBe(404);
    expect((await reconcile("nope")).status).toBe(400);
  });

  it("reconciles a payer-less intent: two senders → ambiguous with candidate evidence and zero received", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    wire(chainProvider);
    const withoutPayer: Record<string, unknown> = { ...validBody, amount: "100.00" };
    delete withoutPayer["payer"];
    const created = (await (await post(withoutPayer)).json()) as { id: string; payer: null };
    expect(created.payer).toBeNull();

    chainProvider.state.latestBlock = 200n;
    chainProvider.state.transfers = [
      { txHash: `0x${"a".repeat(64)}`, logIndex: 1, blockNumber: 110n, blockHash: `0x${"f".repeat(64)}`, from: PAYER.toLowerCase(), to: RECIPIENT.toLowerCase(), amountUnits: 100_000_000n },
      { txHash: `0x${"b".repeat(64)}`, logIndex: 2, blockNumber: 120n, blockHash: `0x${"f".repeat(64)}`, from: "0x1111111111111111111111111111111111111111", to: RECIPIENT.toLowerCase(), amountUnits: 5_000_000n },
    ];
    const response = await reconcile(created.id);
    expect(response.status).toBe(200);
    const body = (await response.json()) as Record<string, unknown>;
    expect(body).toMatchObject({
      status: "ambiguous",
      matchConfidence: "ambiguous",
      expectedAmount: "100.00",
      receivedAmount: "0.00",
      remainingAmount: "100.00",
      payer: null,
      paidAt: null,
    });

    const evidenceBody = (await (await evidence(created.id)).json()) as { evidence: Array<Record<string, unknown>> };
    expect(evidenceBody.evidence.map((row) => [row["from"], row["amount"], row["association"]])).toEqual([
      [PAYER, "100.00", "candidate"],
      ["0x1111111111111111111111111111111111111111", "5.00", "candidate"],
    ]);
  });

  it("reconciles a payer-less intent: one sender → single_sender and paid", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    wire(chainProvider);
    const withoutPayer: Record<string, unknown> = { ...validBody, amount: "25.00" };
    delete withoutPayer["payer"];
    const created = (await (await post(withoutPayer)).json()) as { id: string };
    chainProvider.state.latestBlock = 200n;
    chainProvider.state.transfers = [
      { txHash: `0x${"a".repeat(64)}`, logIndex: 1, blockNumber: 110n, blockHash: `0x${"f".repeat(64)}`, from: PAYER.toLowerCase(), to: RECIPIENT.toLowerCase(), amountUnits: 25_000_000n },
    ];
    chainProvider.state.timestamps = new Map([[110n, new Date("2026-09-18T08:00:00.000Z")]]);
    const body = (await (await reconcile(created.id)).json()) as Record<string, unknown>;
    expect(body).toMatchObject({ status: "paid", matchConfidence: "single_sender", receivedAmount: "25.00", remainingAmount: "0.00", paidAt: "2026-09-18T08:00:00.000Z", payer: null });
  });
});

describe("GET /v1/payment-intents/:id/evidence", () => {
  async function seededIntent() {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    wire(chainProvider);
    const created = (await (await post({ ...validBody, amount: "3.00" })).json()) as { id: string };
    chainProvider.state.latestBlock = 200n;
    chainProvider.state.transfers = [1, 2, 3].map((i) => ({
      txHash: `0x${String(i).repeat(64)}`,
      logIndex: i,
      blockNumber: 110n + BigInt(i),
      blockHash: `0x${"f".repeat(64)}`,
      from: PAYER.toLowerCase(),
      to: RECIPIENT.toLowerCase(),
      amountUnits: 1_000_000n,
    }));
    expect((await reconcile(created.id)).status).toBe(200);
    return created.id;
  }

  it("returns evidence in canonical order with the public shape", async () => {
    const id = await seededIntent();
    const response = await evidence(id);
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    const body = (await response.json()) as { evidence: Array<Record<string, unknown>>; nextCursor: string | null };
    expect(body.nextCursor).toBeNull();
    expect(body.evidence).toHaveLength(3);
    expect(body.evidence[0]).toEqual({
      transactionHash: `0x${"1".repeat(64)}`,
      logIndex: 1,
      blockNumber: "111",
      from: PAYER,
      to: RECIPIENT,
      amount: "1.00",
      confirmations: 90,
      blockTimestamp: new Date(111 * 2_000).toISOString(),
      association: "matched",
    });
    expect(body.evidence.map((row) => row["blockNumber"])).toEqual(["111", "112", "113"]);
  });

  it("paginates with limit and an opaque cursor", async () => {
    const id = await seededIntent();
    const first = (await (await evidence(id, "?limit=2")).json()) as { evidence: Array<{ blockNumber: string }>; nextCursor: string | null };
    expect(first.evidence.map((row) => row.blockNumber)).toEqual(["111", "112"]);
    expect(first.nextCursor).toMatch(/^[A-Za-z0-9_-]+$/);

    const second = (await (await evidence(id, `?limit=2&cursor=${first.nextCursor}`)).json()) as {
      evidence: Array<{ blockNumber: string }>;
      nextCursor: string | null;
    };
    expect(second.evidence.map((row) => row.blockNumber)).toEqual(["113"]);
    expect(second.nextCursor).toBeNull();
  });

  it("rejects a bad limit or cursor with 400 and unknown intents with 404", async () => {
    const id = await seededIntent();
    expect((await evidence(id, "?limit=0")).status).toBe(400);
    expect((await evidence(id, "?limit=101")).status).toBe(400);
    expect((await evidence(id, "?cursor=garbage")).status).toBe(400);
    expect((await evidence(newPaymentIntentId())).status).toBe(404);
    expect((await evidence("nope")).status).toBe(400);
  });
});

describe("abuse hardening (Milestone 5)", () => {
  it("an oversized create body is rejected before validation, services or providers run", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 1n, transfers: [] });
    const repository = wire(chainProvider);
    const huge = JSON.stringify({ ...validBody, externalReference: "x".repeat(20_000) });
    const response = await post(huge);
    expect(response.status).toBe(400);
    const envelope = (await response.json()) as { error: { code: string; message: string } };
    expect(envelope.error.code).toBe("VALIDATION_ERROR");
    expect(envelope.error.message).toMatch(/must not exceed 16384 bytes/);
    expect(chainProvider.calls).toBe(0);
    expect(repository.intents.size).toBe(0);
  });

  it("a create body exactly at 16 KiB is processed normally", async () => {
    wire(new FakeChainProvider({ latestBlock: 1n, transfers: [] }));
    const padded = { ...validBody, externalReference: "x".repeat(100) };
    let body = JSON.stringify(padded);
    // Pad the reference so the serialized body is exactly the limit.
    padded.externalReference = "x".repeat(100 + (16_384 - Buffer.byteLength(body)));
    body = JSON.stringify(padded);
    expect(Buffer.byteLength(body)).toBe(16_384);
    const response = await post(body);
    expect(response.status).toBe(400); // exceeds the 128-character reference limit — but only *after* the body was read
    const envelope = (await response.json()) as { error: { message: string } };
    expect(envelope.error.message).toMatch(/externalReference/);
  });

  it("reconcile rejects a request body without running the service", async () => {
    const chainProvider = new FakeChainProvider({ latestBlock: 100n, transfers: [] });
    wire(chainProvider);
    const created = (await (await post(validBody)).json()) as { id: string };
    const callsAfterCreate = chainProvider.calls;
    const response = await POST_RECONCILE(
      new Request(`http://localhost/v1/payment-intents/${created.id}/reconcile`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ force: true }),
      }),
      { params: Promise.resolve({ id: created.id }) },
    );
    expect(response.status).toBe(400);
    expect(chainProvider.calls).toBe(callsAfterCreate);
  });

  it("malformed IDs are rejected before any repository access on every intent route", async () => {
    const repository = wire(new FakeChainProvider({ latestBlock: 1n, transfers: [] }));
    const spy = vi.spyOn(repository, "getPaymentIntentById");
    for (const bad of ["1", "pi_short", `pi_${"a".repeat(33)}`, "550e8400-e29b-41d4-a716-446655440000", "pi_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA+"]) {
      expect((await get(bad)).status).toBe(400);
      expect((await reconcile(bad)).status).toBe(400);
      expect((await evidence(bad)).status).toBe(400);
    }
    expect(spy).not.toHaveBeenCalled();
  });

  it("every API response is uncacheable and carries no CORS wildcard", async () => {
    wire(new FakeChainProvider({ latestBlock: 100n, transfers: [] }));
    const created = (await (await post(validBody)).json()) as { id: string };
    for (const response of [await get(created.id), await reconcile(created.id), await evidence(created.id), await get("nope")]) {
      expect(response.headers.get("cache-control")).toBe("no-store");
      expect(response.headers.get("access-control-allow-origin")).toBeNull();
      expect(response.headers.get("x-request-id")).toMatch(/^req_/);
    }
  });

  it("an unexpected internal failure yields the generic envelope, never the underlying message", async () => {
    const repository = wire(new FakeChainProvider({ latestBlock: 100n, transfers: [] }));
    const created = (await (await post(validBody)).json()) as { id: string };
    repository.getPaymentIntentById = async () => {
      throw new Error("Failed query: select … params: secret-looking-value postgres://u:p@h/db");
    };
    const response = await get(created.id);
    expect(response.status).toBe(500);
    const text = await response.text();
    expect(JSON.parse(text)).toEqual({ error: { code: "INTERNAL_ERROR", message: "Unexpected internal error", retryable: false } });
    expect(text).not.toContain("postgres://");
    expect(text).not.toContain("secret-looking");
  });
});
