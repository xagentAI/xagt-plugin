/**
 * Environment validation. This is the only module that reads `process.env`
 * for application configuration (ARCHITECTURE.md §11 "Configuration").
 *
 * Chain ID, token contract, decimals, confirmation defaults, expiry limits and
 * body limits are code constants, never environment variables.
 */
import "server-only";

import { z } from "zod";

import { AppError } from "./errors";
import { LOG_LEVELS, type LogLevel } from "./logger";

const GIT_COMMIT_SHA = /^[0-9a-f]{40}$/;

const envSchema = z.object({
  NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
  // Platform-provided on Vercel.
  VERCEL_ENV: z.enum(["development", "preview", "production"]).optional(),
  VERCEL_GIT_COMMIT_SHA: z
    .string()
    .regex(GIT_COMMIT_SHA, "must be the 40-character lowercase hex git commit SHA")
    .optional(),
  // Required in production for the X-Agent verification route; the route
  // itself returns 500 when it is absent (ARCHITECTURE.md §14).
  XAGENT_SLUG: z.string().trim().min(1).optional(),
  LOG_LEVEL: z.enum(LOG_LEVELS).default("info"),
  // Neon pooled runtime connection (application queries).
  DATABASE_URL: z.url({ protocol: /^postgres(ql)?$/, error: "must be a postgres:// URL" }),
  // Neon direct connection; used only by migration tooling (drizzle.config.ts).
  DATABASE_URL_UNPOOLED: z.url({ protocol: /^postgres(ql)?$/, error: "must be a postgres:// URL" }),
  // Server-only Base mainnet RPC endpoint; contains the provider credential.
  ALCHEMY_BASE_RPC_URL: z.url({ protocol: /^https?$/, error: "must be an http(s) URL" }),
});

/** Raw environment input; `process.env` or an explicit map in tests. */
export type EnvironmentSource = Readonly<Record<string, string | undefined>>;

export type DeploymentEnvironment = "development" | "preview" | "production" | "test";

export interface AppConfig {
  readonly nodeEnv: "development" | "test" | "production";
  /** `VERCEL_ENV` when deployed; otherwise derived from `NODE_ENV`. */
  readonly deploymentEnv: DeploymentEnvironment;
  /** Exact 40-character git commit SHA of the deployed build, or `null` when not deployed. */
  readonly commitSha: string | null;
  /** Registered hackathon slug, or `null` when not configured. */
  readonly xagentSlug: string | null;
  readonly logLevel: LogLevel;
  /** Secrets: never log these or echo them in any response. */
  readonly databaseUrl: string;
  readonly databaseUrlUnpooled: string;
  readonly alchemyBaseRpcUrl: string;
}

export class ConfigError extends AppError {
  readonly issues: readonly string[];

  constructor(issues: readonly string[]) {
    // Client-facing message stays generic; the issue list goes to logs only.
    super("INTERNAL_ERROR", "Server configuration is invalid", { context: { issues } });
    this.name = "ConfigError";
    this.issues = issues;
  }
}

/** Treats empty-string variables (common in `.env` files and dashboards) as unset. */
function withoutEmptyValues(env: EnvironmentSource): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(env)) {
    if (value !== undefined && value !== "") {
      out[key] = value;
    }
  }
  return out;
}

/**
 * Parses and validates configuration from `env`. Throws `ConfigError` listing
 * the offending variable names (never their values).
 */
export function loadConfig(env: EnvironmentSource = process.env): AppConfig {
  const parsed = envSchema.safeParse(withoutEmptyValues(env));
  if (!parsed.success) {
    const issues = parsed.error.issues.map(
      (issue) => `${issue.path.map(String).join(".") || "(root)"}: ${issue.message}`,
    );
    throw new ConfigError(issues);
  }

  const {
    NODE_ENV,
    VERCEL_ENV,
    VERCEL_GIT_COMMIT_SHA,
    XAGENT_SLUG,
    LOG_LEVEL,
    DATABASE_URL,
    DATABASE_URL_UNPOOLED,
    ALCHEMY_BASE_RPC_URL,
  } = parsed.data;
  const deploymentEnv: DeploymentEnvironment =
    VERCEL_ENV ?? (NODE_ENV === "test" ? "test" : "development");

  return {
    nodeEnv: NODE_ENV,
    deploymentEnv,
    commitSha: VERCEL_GIT_COMMIT_SHA ?? null,
    xagentSlug: XAGENT_SLUG ?? null,
    logLevel: LOG_LEVEL,
    databaseUrl: DATABASE_URL,
    databaseUrlUnpooled: DATABASE_URL_UNPOOLED,
    alchemyBaseRpcUrl: ALCHEMY_BASE_RPC_URL,
  };
}

let cached: AppConfig | undefined;

/** Validates `process.env` once per process and returns the cached result. */
export function getConfig(): AppConfig {
  cached ??= loadConfig();
  return cached;
}

/** Test hook: forces the next `getConfig()` call to re-read `process.env`. */
export function resetConfigCache(): void {
  cached = undefined;
}
