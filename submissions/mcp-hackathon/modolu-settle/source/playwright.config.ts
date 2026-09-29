import { defineConfig } from "@playwright/test";

/**
 * Browser smoke suite (ARCHITECTURE.md §13 "E2E smoke tests"). Runs against
 * a production build served locally with placeholder secrets; every `/v1/*`
 * call the pages make is intercepted in the browser with fixtures, so no
 * Neon database or Alchemy credential is needed. Production code has no
 * test switches — interception happens entirely inside Playwright.
 */
const PORT = 3300;
const BASE_URL = `http://localhost:${PORT}`;

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /.*\.spec\.ts/,
  fullyParallel: true,
  forbidOnly: !!process.env["CI"],
  retries: process.env["CI"] ? 1 : 0,
  reporter: process.env["CI"] ? "github" : "list",
  timeout: 30_000,
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
  },
  projects: [
    { name: "desktop", use: { browserName: "chromium", viewport: { width: 1440, height: 900 } } },
    { name: "mobile", use: { browserName: "chromium", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: `pnpm exec next build && pnpm exec next start -p ${PORT}`,
    url: `${BASE_URL}/health`,
    reuseExistingServer: !process.env["CI"],
    timeout: 240_000,
    env: {
      // Placeholders satisfy config validation; the suite never dials them.
      DATABASE_URL: "postgres://settle:placeholder@localhost:5432/settle",
      DATABASE_URL_UNPOOLED: "postgres://settle:placeholder@localhost:5432/settle",
      ALCHEMY_BASE_RPC_URL: "https://base-mainnet.example.invalid/v2/placeholder",
      XAGENT_SLUG: "modolu-settle",
      VERCEL_GIT_COMMIT_SHA: "0123456789abcdef0123456789abcdef01234567",
      LOG_LEVEL: "warn",
    },
  },
});
