import { describe, expect, it } from "vitest";

import { ConfigError, loadConfig } from "@/lib/config";

const SHA = "0123456789abcdef0123456789abcdef01234567";

/** The Milestone 1 secrets every environment must provide. */
const secrets = {
  DATABASE_URL: "postgres://user:pooled-secret@ep-pooler.neon.tech/settle?sslmode=require",
  DATABASE_URL_UNPOOLED: "postgresql://user:direct-secret@ep-direct.neon.tech/settle?sslmode=require",
  ALCHEMY_BASE_RPC_URL: "https://base-mainnet.g.alchemy.com/v2/alchemy-secret-key",
};

describe("loadConfig", () => {
  it("applies defaults when only the required secrets are set", () => {
    const config = loadConfig(secrets);
    expect(config).toEqual({
      nodeEnv: "development",
      deploymentEnv: "development",
      commitSha: null,
      xagentSlug: null,
      logLevel: "info",
      databaseUrl: secrets.DATABASE_URL,
      databaseUrlUnpooled: secrets.DATABASE_URL_UNPOOLED,
      alchemyBaseRpcUrl: secrets.ALCHEMY_BASE_RPC_URL,
    });
  });

  it("requires DATABASE_URL, DATABASE_URL_UNPOOLED and ALCHEMY_BASE_RPC_URL", () => {
    expect(() => loadConfig({})).toThrow(ConfigError);
    for (const key of Object.keys(secrets)) {
      const env: Record<string, string> = { ...secrets };
      delete env[key];
      let caught: unknown;
      try {
        loadConfig(env);
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(ConfigError);
      expect((caught as ConfigError).issues).toEqual([expect.stringMatching(new RegExp(`^${key}: `)) as string]);
    }
  });

  it("rejects secrets with the wrong URL scheme without echoing their values", () => {
    for (const env of [
      { ...secrets, DATABASE_URL: "mysql://user:pw@host/db" },
      { ...secrets, DATABASE_URL_UNPOOLED: "not a url" },
      { ...secrets, ALCHEMY_BASE_RPC_URL: "wss://base-mainnet.g.alchemy.com/v2/key" },
    ]) {
      let caught: unknown;
      try {
        loadConfig(env);
      } catch (error) {
        caught = error;
      }
      expect(caught).toBeInstanceOf(ConfigError);
      const text = JSON.stringify((caught as ConfigError).issues);
      expect(text).not.toMatch(/pw@host|not a url|alchemy\.com/);
    }
  });

  it("reads Vercel platform variables", () => {
    const config = loadConfig({
      ...secrets,
      NODE_ENV: "production",
      VERCEL_ENV: "production",
      VERCEL_GIT_COMMIT_SHA: SHA,
      XAGENT_SLUG: "settle",
      LOG_LEVEL: "debug",
    });
    expect(config).toEqual({
      nodeEnv: "production",
      deploymentEnv: "production",
      commitSha: SHA,
      xagentSlug: "settle",
      logLevel: "debug",
      databaseUrl: secrets.DATABASE_URL,
      databaseUrlUnpooled: secrets.DATABASE_URL_UNPOOLED,
      alchemyBaseRpcUrl: secrets.ALCHEMY_BASE_RPC_URL,
    });
  });

  it("derives the test deployment environment from NODE_ENV when not on Vercel", () => {
    expect(loadConfig({ ...secrets, NODE_ENV: "test" }).deploymentEnv).toBe("test");
  });

  it("treats empty-string variables as unset", () => {
    const config = loadConfig({ ...secrets, VERCEL_GIT_COMMIT_SHA: "", XAGENT_SLUG: "", LOG_LEVEL: "" });
    expect(config.commitSha).toBeNull();
    expect(config.xagentSlug).toBeNull();
    expect(config.logLevel).toBe("info");
  });

  it("rejects a commit SHA that is not 40 lowercase hex characters", () => {
    expect(() => loadConfig({ ...secrets, VERCEL_GIT_COMMIT_SHA: "abc123" })).toThrow(ConfigError);
    expect(() => loadConfig({ ...secrets, VERCEL_GIT_COMMIT_SHA: SHA.toUpperCase() })).toThrow(ConfigError);
  });

  it("rejects unknown LOG_LEVEL and NODE_ENV values", () => {
    expect(() => loadConfig({ ...secrets, LOG_LEVEL: "verbose" })).toThrow(ConfigError);
    expect(() => loadConfig({ ...secrets, NODE_ENV: "staging" })).toThrow(ConfigError);
  });

  it("names offending variables but never their values", () => {
    let caught: unknown;
    try {
      loadConfig({ ...secrets, VERCEL_GIT_COMMIT_SHA: "not-a-sha-value", LOG_LEVEL: "loud" });
    } catch (error) {
      caught = error;
    }
    expect(caught).toBeInstanceOf(ConfigError);
    const error = caught as ConfigError;
    expect(error.code).toBe("INTERNAL_ERROR");
    expect(error.httpStatus).toBe(500);
    expect(error.message).toBe("Server configuration is invalid");
    expect(error.issues).toHaveLength(2);
    expect(error.issues.join("\n")).toMatch(/VERCEL_GIT_COMMIT_SHA/);
    expect(error.issues.join("\n")).toMatch(/LOG_LEVEL/);
    expect(error.issues.join("\n")).not.toMatch(/not-a-sha-value|loud/);
  });
});
