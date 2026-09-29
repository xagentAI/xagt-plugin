import { z } from "zod";

// Development builds use an all-zero placeholder. Deployments can provide the
// reviewed commit explicitly or use Render's immutable Git commit metadata.
const defaultDevelopmentCommit = "0000000000000000000000000000000000000000";
const commitSchema = z
  .string()
  .regex(/^[0-9a-f]{40}$/i, "Commit metadata must be a 40-character Git SHA");

// Parse environment variables once at startup so invalid configuration fails
// early instead of producing ambiguous errors while handling a request.
const envSchema = z
  .object({
    NODE_ENV: z.enum(["development", "test", "production"]).default("development"),
    HOST: z.string().min(1).default("0.0.0.0"),
    PORT: z.coerce.number().int().min(1).max(65_535).default(3_000),
    GITHUB_TOKEN: z.string().min(1).optional(),
    SOURCE_COMMIT: commitSchema.optional(),
    RENDER_GIT_COMMIT: commitSchema.optional(),
    PROJECT_SLUG: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/).default("bountylens"),
    CACHE_TTL_SECONDS: z.coerce.number().int().positive().default(300),
    REQUEST_TIMEOUT_MS: z.coerce.number().int().positive().default(10_000),
  })
  .superRefine((environment, context) => {
    if (
      environment.NODE_ENV === "production" &&
      (environment.SOURCE_COMMIT ?? environment.RENDER_GIT_COMMIT) === undefined
    ) {
      context.addIssue({
        code: "custom",
        path: ["SOURCE_COMMIT"],
        message: "Production SOURCE_COMMIT must identify the reviewed source commit.",
      });
    }
  });

export type AppConfig = {
  nodeEnv: "development" | "test" | "production";
  host: string;
  port: number;
  githubToken: string | undefined;
  sourceCommit: string;
  projectSlug: string;
  cacheTtlSeconds: number;
  requestTimeoutMs: number;
};

/** Convert process.env strings into the typed configuration used by the app. */
export function loadConfig(environment: NodeJS.ProcessEnv = process.env): AppConfig {
  const parsed = envSchema.parse(environment);

  return {
    nodeEnv: parsed.NODE_ENV,
    host: parsed.HOST,
    port: parsed.PORT,
    githubToken: parsed.GITHUB_TOKEN,
    sourceCommit:
      parsed.SOURCE_COMMIT ?? parsed.RENDER_GIT_COMMIT ?? defaultDevelopmentCommit,
    projectSlug: parsed.PROJECT_SLUG,
    cacheTtlSeconds: parsed.CACHE_TTL_SECONDS,
    requestTimeoutMs: parsed.REQUEST_TIMEOUT_MS,
  };
}
