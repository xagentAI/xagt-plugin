import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors";
import { MAX_JSON_BODY_BYTES, readJsonBody } from "@/lib/request-body";

function jsonRequest(body: BodyInit | null, headers: Record<string, string> = {}): Request {
  return new Request("http://localhost/v1/payment-intents", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body,
  });
}

async function expectValidationError(promise: Promise<unknown>, pattern: RegExp): Promise<void> {
  let caught: unknown;
  try {
    await promise;
  } catch (error) {
    caught = error;
  }
  expect(caught).toBeInstanceOf(AppError);
  expect((caught as AppError).code).toBe("VALIDATION_ERROR");
  expect((caught as AppError).message).toMatch(pattern);
}

describe("readJsonBody", () => {
  it("fixes the body limit at 16 KiB", () => {
    expect(MAX_JSON_BODY_BYTES).toBe(16_384);
  });

  it("parses a JSON object", async () => {
    await expect(readJsonBody(jsonRequest(JSON.stringify({ amount: "1" })))).resolves.toEqual({ amount: "1" });
  });

  it("accepts a charset parameter on the content type", async () => {
    await expect(
      readJsonBody(jsonRequest("{}", { "content-type": "application/json; charset=utf-8" })),
    ).resolves.toEqual({});
  });

  it("rejects a non-JSON content type", async () => {
    await expectValidationError(readJsonBody(jsonRequest("{}", { "content-type": "text/plain" })), /Content-Type/);
    await expectValidationError(
      readJsonBody(new Request("http://localhost/x", { method: "POST", body: "{}" })),
      /Content-Type/,
    );
  });

  it("rejects an empty body", async () => {
    await expectValidationError(readJsonBody(jsonRequest(null)), /JSON object/);
    await expectValidationError(readJsonBody(jsonRequest("")), /JSON object/);
  });

  it("rejects malformed JSON and invalid UTF-8", async () => {
    await expectValidationError(readJsonBody(jsonRequest("{oops")), /not valid JSON/);
    await expectValidationError(readJsonBody(jsonRequest(new Uint8Array([0xff, 0xfe, 0x7b]))), /not valid JSON/);
  });

  it("accepts a body exactly at the limit and rejects one byte over", async () => {
    const atLimit = `{"a":"${"x".repeat(MAX_JSON_BODY_BYTES - 8)}"}`;
    expect(Buffer.byteLength(atLimit)).toBe(MAX_JSON_BODY_BYTES);
    await expect(readJsonBody(jsonRequest(atLimit))).resolves.toBeTypeOf("object");

    const overLimit = `{"a":"${"x".repeat(MAX_JSON_BODY_BYTES - 7)}"}`;
    expect(Buffer.byteLength(overLimit)).toBe(MAX_JSON_BODY_BYTES + 1);
    await expectValidationError(readJsonBody(jsonRequest(overLimit)), /must not exceed/);
  });

  it("enforces the limit while streaming, ignoring an understated Content-Length", async () => {
    const chunk = new TextEncoder().encode("x".repeat(4096));
    let sent = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        if (sent >= 10) {
          controller.close();
          return;
        }
        sent += 1;
        controller.enqueue(chunk);
      },
    });
    const request = new Request("http://localhost/x", {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": "10" },
      body: stream,
      // @ts-expect-error -- undici requires duplex for streaming bodies; not in lib.dom types
      duplex: "half",
    });
    await expectValidationError(readJsonBody(request), /must not exceed/);
    expect(sent).toBeLessThan(10);
  });

  it("rejects early on an overstated Content-Length", async () => {
    await expectValidationError(
      readJsonBody(jsonRequest("{}", { "content-length": String(MAX_JSON_BODY_BYTES + 1) })),
      /must not exceed/,
    );
  });
});

// ---------------------------------------------------------------------------
// Milestone 5: abuse hardening
// ---------------------------------------------------------------------------
import { assertNoRequestBody } from "@/lib/request-body";

function streamingRequest(chunks: Uint8Array[], headers: Record<string, string> = {}): Request {
  let index = 0;
  const stream = new ReadableStream<Uint8Array>({
    pull(controller) {
      const chunk = chunks[index];
      if (chunk === undefined) {
        controller.close();
        return;
      }
      index += 1;
      controller.enqueue(chunk);
    },
  });
  return new Request("http://localhost/x", {
    method: "POST",
    headers: { "content-type": "application/json", ...headers },
    body: stream,
    // @ts-expect-error -- undici requires duplex for streaming bodies; not in lib.dom types
    duplex: "half",
  });
}

describe("readJsonBody — limit cannot be bypassed", () => {
  it("enforces the limit on a streamed body with no Content-Length at all", async () => {
    const chunk = new TextEncoder().encode("x".repeat(4096));
    const request = streamingRequest(Array.from({ length: 10 }, () => chunk));
    expect(request.headers.get("content-length")).toBeNull();
    await expectValidationError(readJsonBody(request), /must not exceed/);
  });

  it("enforces the limit when Content-Length understates the body", async () => {
    const chunk = new TextEncoder().encode("x".repeat(4096));
    const request = streamingRequest(Array.from({ length: 5 }, () => chunk), { "content-length": "1" });
    await expectValidationError(readJsonBody(request), /must not exceed/);
  });

  it("accepts a streamed body exactly at the limit even without Content-Length", async () => {
    const text = `{"a":"${"x".repeat(MAX_JSON_BODY_BYTES - 8)}"}`;
    const bytes = new TextEncoder().encode(text);
    expect(bytes.byteLength).toBe(MAX_JSON_BODY_BYTES);
    const request = streamingRequest([bytes.slice(0, 5000), bytes.slice(5000, 12000), bytes.slice(12000)]);
    await expect(readJsonBody(request)).resolves.toEqual({ a: "x".repeat(MAX_JSON_BODY_BYTES - 8) });
  });

  it("rejects one byte over the limit on a streamed body without Content-Length", async () => {
    const bytes = new TextEncoder().encode(`{"a":"${"x".repeat(MAX_JSON_BODY_BYTES - 7)}"}`);
    expect(bytes.byteLength).toBe(MAX_JSON_BODY_BYTES + 1);
    await expectValidationError(readJsonBody(streamingRequest([bytes])), /must not exceed/);
  });
});

describe("assertNoRequestBody", () => {
  it("accepts a bodiless request", async () => {
    await expect(assertNoRequestBody(new Request("http://localhost/x", { method: "POST" }))).resolves.toBeUndefined();
  });

  it("rejects a declared body before reading it", async () => {
    const request = new Request("http://localhost/x", { method: "POST", body: "{}", headers: { "content-type": "application/json" } });
    await expectValidationError(assertNoRequestBody(request), /does not accept a request body/);
  });

  it("rejects a streamed body with no Content-Length after the first chunk, without draining it", async () => {
    let pulls = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls += 1;
        controller.enqueue(new TextEncoder().encode("x".repeat(1024)));
      },
    });
    const request = new Request("http://localhost/x", {
      method: "POST",
      body: stream,
      // @ts-expect-error -- undici requires duplex for streaming bodies; not in lib.dom types
      duplex: "half",
    });
    await expectValidationError(assertNoRequestBody(request), /does not accept a request body/);
    expect(pulls).toBeLessThanOrEqual(2);
  });
});
