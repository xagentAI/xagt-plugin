import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // `import "server-only"` throws outside React Server Components; tests
      // exercise server modules directly, so resolve it to the package's
      // own empty module (the one Next.js uses on the server).
      "server-only": fileURLToPath(new URL("./node_modules/server-only/empty.js", import.meta.url)),
    },
  },
  test: {
    environment: "node",
    include: ["tests/**/*.test.{ts,tsx}"],
    env: {
      // Keep test output free of application log lines.
      LOG_LEVEL: "silent",
      // Placeholder secrets so config validation passes; unit tests never dial
      // these. Integration tests use TEST_DATABASE_URL explicitly.
      DATABASE_URL: "postgres://settle:placeholder@localhost:5432/settle",
      DATABASE_URL_UNPOOLED: "postgres://settle:placeholder@localhost:5432/settle",
      ALCHEMY_BASE_RPC_URL: "https://base-mainnet.example.invalid/v2/placeholder",
    },
  },
});
