import { describe, expect, it } from "vitest";

import { AppError } from "@/lib/errors";
import {
  XAGENT_SCHEMA_VERSION,
  XAGENT_SLUG,
  buildXagentVerification,
  xagentVerificationSchema,
} from "@/lib/xagent-verification";

const SHA = "0123456789abcdef0123456789abcdef01234567";

function captureAppError(fn: () => unknown): AppError {
  try {
    fn();
  } catch (error) {
    expect(error).toBeInstanceOf(AppError);
    return error as AppError;
  }
  return expect.unreachable("expected an AppError");
}

describe("buildXagentVerification (official schema)", () => {
  it("fixes the registered slug and schema version", () => {
    expect(XAGENT_SLUG).toBe("modolu-settle");
    expect(XAGENT_SCHEMA_VERSION).toBe(1);
  });

  it("returns exactly schemaVersion, slug and commit for a valid 40-character commit", () => {
    const document = buildXagentVerification({ xagentSlug: "modolu-settle", commitSha: SHA });
    expect(document).toEqual({ schemaVersion: 1, slug: "modolu-settle", commit: SHA });
    expect(Object.keys(document)).toEqual(["schemaVersion", "slug", "commit"]);
    expect(xagentVerificationSchema.safeParse(document).success).toBe(true);
  });

  it("fails when the slug is missing", () => {
    const error = captureAppError(() => buildXagentVerification({ xagentSlug: null, commitSha: SHA }));
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.httpStatus).toBe(500);
    expect(error.message).toBe("X-Agent verification is not configured: missing XAGENT_SLUG");
  });

  it("fails when the configured slug is not the registered one", () => {
    for (const slug of ["settle", "Modolu-Settle", "modolu-settle ", "modolu-settle-2"]) {
      const error = captureAppError(() => buildXagentVerification({ xagentSlug: slug, commitSha: SHA }));
      expect(error.code).toBe("INTERNAL_ERROR");
      expect(error.message).toBe('X-Agent verification is misconfigured: XAGENT_SLUG must be "modolu-settle"');
    }
  });

  it("fails when the commit is missing", () => {
    const error = captureAppError(() => buildXagentVerification({ xagentSlug: "modolu-settle", commitSha: null }));
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.message).toBe("X-Agent verification is not configured: missing VERCEL_GIT_COMMIT_SHA");
  });

  it("lists both variables when neither is configured", () => {
    const error = captureAppError(() => buildXagentVerification({ xagentSlug: null, commitSha: null }));
    expect(error.message).toBe("X-Agent verification is not configured: missing XAGENT_SLUG, VERCEL_GIT_COMMIT_SHA");
  });

  it("never emits a malformed commit (belt and braces behind config validation)", () => {
    for (const commitSha of ["abc123", SHA.toUpperCase(), `${SHA}0`, SHA.slice(0, 39)]) {
      expect(() => buildXagentVerification({ xagentSlug: "modolu-settle", commitSha })).toThrow();
    }
  });

  it("schema rejects extra fields, other slugs, other schema versions and malformed commits", () => {
    const valid = { schemaVersion: 1, slug: "modolu-settle", commit: SHA };
    expect(xagentVerificationSchema.safeParse(valid).success).toBe(true);
    expect(xagentVerificationSchema.safeParse({ ...valid, extra: 1 }).success).toBe(false);
    expect(xagentVerificationSchema.safeParse({ ...valid, slug: "settle" }).success).toBe(false);
    expect(xagentVerificationSchema.safeParse({ ...valid, schemaVersion: 2 }).success).toBe(false);
    expect(xagentVerificationSchema.safeParse({ ...valid, schemaVersion: "1" }).success).toBe(false);
    expect(xagentVerificationSchema.safeParse({ ...valid, commit: "abc" }).success).toBe(false);
    expect(xagentVerificationSchema.safeParse({ slug: "modolu-settle", commit: SHA }).success).toBe(false);
  });
});
