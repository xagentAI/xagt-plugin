/**
 * drizzle-kit configuration (`pnpm db:generate`, `pnpm db:migrate`).
 * Migrations connect through the direct (unpooled) Neon URL. `.env.local`
 * is loaded when present without overriding variables already exported.
 */
import { existsSync } from "node:fs";

import { defineConfig } from "drizzle-kit";

if (existsSync(".env.local")) {
  process.loadEnvFile(".env.local");
}

export default defineConfig({
  dialect: "postgresql",
  schema: "./src/db/schema.ts",
  out: "./drizzle",
  strict: true,
  verbose: true,
  dbCredentials: {
    // Only `db:migrate` dials the database; `db:generate` works without it.
    url: process.env["DATABASE_URL_UNPOOLED"] ?? "",
  },
});
