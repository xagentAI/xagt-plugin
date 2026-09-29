import { describe, expect, it } from "vitest";

import { createLogger, isLogLevel, parseLogLevel, type LogLevel } from "@/lib/logger";

function capture() {
  const lines: Array<{ line: string; level: LogLevel }> = [];
  const write = (line: string, level: LogLevel): void => {
    lines.push({ line, level });
  };
  return { lines, write };
}

describe("createLogger", () => {
  it("emits one single-line JSON object per call with level, time and msg", () => {
    const { lines, write } = capture();
    createLogger({ level: "debug", write }).info("hello", { requestId: "req_1" });

    expect(lines).toHaveLength(1);
    const [entry] = lines;
    expect(entry?.line.includes("\n")).toBe(false);
    const parsed = JSON.parse(entry?.line ?? "") as Record<string, unknown>;
    expect(parsed["level"]).toBe("info");
    expect(parsed["msg"]).toBe("hello");
    expect(parsed["requestId"]).toBe("req_1");
    expect(typeof parsed["time"]).toBe("string");
    expect(() => new Date(parsed["time"] as string).toISOString()).not.toThrow();
  });

  it("filters entries below the configured level", () => {
    const { lines, write } = capture();
    const log = createLogger({ level: "warn", write });
    log.debug("d");
    log.info("i");
    log.warn("w");
    log.error("e");
    expect(lines.map((entry) => entry.level)).toEqual(["warn", "error"]);
  });

  it("emits nothing at level silent", () => {
    const { lines, write } = capture();
    const log = createLogger({ level: "silent", write });
    log.error("e");
    expect(lines).toHaveLength(0);
  });

  it("includes child bindings on every line and lets fields override them", () => {
    const { lines, write } = capture();
    const log = createLogger({ level: "info", write }).child({ route: "/health", method: "GET" });
    log.info("a");
    log.info("b", { method: "POST" });
    const [first, second] = lines.map((entry) => JSON.parse(entry.line) as Record<string, unknown>);
    expect(first).toMatchObject({ route: "/health", method: "GET", msg: "a" });
    expect(second).toMatchObject({ route: "/health", method: "POST", msg: "b" });
  });

  it("serializes bigint values and Error objects", () => {
    const { lines, write } = capture();
    const cause = new Error("root cause");
    const err = new Error("outer", { cause });
    createLogger({ level: "info", write }).error("failed", { units: 850_000_000n, err });
    const parsed = JSON.parse(lines[0]?.line ?? "") as {
      units: unknown;
      err: { name: string; message: string; stack?: string; cause?: { message: string } };
    };
    expect(parsed.units).toBe("850000000");
    expect(parsed.err.name).toBe("Error");
    expect(parsed.err.message).toBe("outer");
    expect(typeof parsed.err.stack).toBe("string");
    expect(parsed.err.cause?.message).toBe("root cause");
  });
});

describe("parseLogLevel", () => {
  it("accepts known levels and falls back to info otherwise", () => {
    expect(parseLogLevel("debug")).toBe("debug");
    expect(parseLogLevel("silent")).toBe("silent");
    expect(parseLogLevel(undefined)).toBe("info");
    expect(parseLogLevel("verbose")).toBe("info");
    expect(isLogLevel("warn")).toBe(true);
    expect(isLogLevel("WARN")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Milestone 5: secret redaction at the logging choke point
// ---------------------------------------------------------------------------
import { redactSecrets } from "@/lib/logger";

const DB_URL = "postgres://settle:hunter2-secret@ep-cool-name.us-east-2.aws.neon.tech/settle?sslmode=require";
const RPC_URL = "https://base-mainnet.g.alchemy.com/v2/AbCdEf123456SecretKey_-";

describe("redactSecrets", () => {
  it("masks credentials embedded in URLs but keeps the host for diagnostics", () => {
    expect(redactSecrets(`connect failed: ${DB_URL}`)).toBe(
      "connect failed: postgres://[redacted]@ep-cool-name.us-east-2.aws.neon.tech/settle?sslmode=require",
    );
  });

  it("masks provider API keys carried in URL paths", () => {
    expect(redactSecrets(`HTTP request failed. URL: ${RPC_URL}`)).toBe(
      "HTTP request failed. URL: https://base-mainnet.g.alchemy.com/v2/[redacted]",
    );
  });

  it("masks environment-style secret assignments", () => {
    expect(redactSecrets(`env: DATABASE_URL=${DB_URL} ALCHEMY_BASE_RPC_URL=${RPC_URL} LOG_LEVEL=info`)).toBe(
      "env: DATABASE_URL=[redacted] ALCHEMY_BASE_RPC_URL=[redacted] LOG_LEVEL=info",
    );
  });

  it("drops query parameters echoed by database driver errors", () => {
    const message = 'Failed query: insert into "payment_intents" (...) values ($1, $2)\nparams: pi_x,INV-204,0x833589fcd6edb6e08f4c7c32d4f71b54bda02913';
    expect(redactSecrets(message)).toBe('Failed query: insert into "payment_intents" (...) values ($1, $2)\nparams: [redacted]');
  });

  it("truncates very long strings", () => {
    expect(redactSecrets("y".repeat(5_000)).length).toBeLessThan(2_100);
  });

  it("is applied to every string in an emitted line, including nested error causes", () => {
    const { lines, write } = capture();
    const cause = new Error(`getaddrinfo ENOTFOUND ${DB_URL}`);
    const outer = new Error(`request to ${RPC_URL} failed`, { cause });
    createLogger({ level: "info", write }).error("boom", { err: outer, note: `saw DATABASE_URL=${DB_URL}` });
    const line = lines[0]?.line ?? "";
    expect(line).not.toContain("hunter2");
    expect(line).not.toContain("SecretKey");
    expect(line).toContain("postgres://[redacted]@ep-cool-name");
    expect(line).toContain("/v2/[redacted]");
    expect(line).toContain("DATABASE_URL=[redacted]");
  });
});
