import { describe, expect, it } from "vitest";

import { AppError, ERROR_CODES, isAppError, toAppError, toErrorEnvelope } from "@/lib/errors";

describe("AppError", () => {
  it("maps every stable code to its HTTP status", () => {
    expect(ERROR_CODES).toEqual({
      VALIDATION_ERROR: 400,
      INVALID_ADDRESS: 400,
      UNSUPPORTED_CHAIN: 400,
      UNSUPPORTED_ASSET: 400,
      INTENT_NOT_FOUND: 404,
      RATE_LIMITED: 429,
      UPSTREAM_UNAVAILABLE: 503,
      UPSTREAM_INVALID_RESPONSE: 502,
      INTERNAL_ERROR: 500,
    });
    for (const [code, status] of Object.entries(ERROR_CODES)) {
      expect(new AppError(code as keyof typeof ERROR_CODES, "x").httpStatus).toBe(status);
    }
  });

  it("marks upstream outages and rate limits retryable by default", () => {
    expect(new AppError("UPSTREAM_UNAVAILABLE", "x").retryable).toBe(true);
    expect(new AppError("RATE_LIMITED", "x").retryable).toBe(true);
    expect(new AppError("UPSTREAM_INVALID_RESPONSE", "x").retryable).toBe(false);
    expect(new AppError("VALIDATION_ERROR", "x").retryable).toBe(false);
    expect(new AppError("INTERNAL_ERROR", "x").retryable).toBe(false);
  });

  it("allows retryable to be overridden and keeps cause/context", () => {
    const cause = new Error("socket hang up");
    const error = new AppError("INTERNAL_ERROR", "x", {
      retryable: true,
      cause,
      context: { attempt: 2 },
    });
    expect(error.retryable).toBe(true);
    expect(error.cause).toBe(cause);
    expect(error.context).toEqual({ attempt: 2 });
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("AppError");
  });
});

describe("toAppError", () => {
  it("passes AppError through unchanged", () => {
    const error = new AppError("INTENT_NOT_FOUND", "no such intent");
    expect(toAppError(error)).toBe(error);
    expect(isAppError(error)).toBe(true);
  });

  it("wraps unknown errors as a generic INTERNAL_ERROR without leaking the message", () => {
    const raw = new Error("connection to db failed: password=hunter2");
    const error = toAppError(raw);
    expect(isAppError(raw)).toBe(false);
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.httpStatus).toBe(500);
    expect(error.message).toBe("Unexpected internal error");
    expect(error.cause).toBe(raw);
  });

  it("wraps non-Error throwables", () => {
    const error = toAppError("boom");
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.cause).toBe("boom");
  });
});

describe("toErrorEnvelope", () => {
  it("produces exactly the public error object", () => {
    const envelope = toErrorEnvelope(
      new AppError("UPSTREAM_UNAVAILABLE", "Blockchain provider is temporarily unavailable", {
        context: { secret: "must not appear" },
      }),
    );
    expect(envelope).toEqual({
      error: {
        code: "UPSTREAM_UNAVAILABLE",
        message: "Blockchain provider is temporarily unavailable",
        retryable: true,
      },
    });
    expect(JSON.stringify(envelope)).not.toContain("must not appear");
  });
});
