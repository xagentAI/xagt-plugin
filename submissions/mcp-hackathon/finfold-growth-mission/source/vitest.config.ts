import { cloudflareTest } from "@cloudflare/vitest-pool-workers";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    cloudflareTest({
      wrangler: { configPath: "./wrangler.test.jsonc" },
      miniflare: {
        compatibilityDate: "2026-08-22",
        d1Databases: ["DB"],
        bindings: {
          APP_BASE_URL: "https://api.finfold.app",
          COMMIT_SHA: "1111111111111111111111111111111111111111",
          MODEL_PROVIDER: "http",
          LLM_API_BASE: "https://llm.test/v1",
          LLM_MODEL: "test-model",
          LLM_API_KEY: "test-only-key",
          SUPPORT_EMAIL: "support@finfold.app",
        },
      },
    }),
  ],
  test: {
    setupFiles: ["./test/setup.ts"],
    coverage: {
      reporter: ["text", "json-summary"]
    }
  }
});
