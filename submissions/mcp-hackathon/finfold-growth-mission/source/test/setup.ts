import { env } from "cloudflare:test";
import { beforeAll } from "vitest";
import migration from "../migrations/0001_initial.sql?raw";
import demoMigration from "../migrations/0002_public_demo.sql?raw";

async function applyMigration(sql: string): Promise<void> {
  const statements = sql
    .replace(/^PRAGMA[^;]+;/gm, "")
    .split(";")
    .map((statement) => statement.trim())
    .filter(Boolean)
    .map((statement) => env.DB.prepare(statement));
  await env.DB.batch(statements);
}

beforeAll(async () => {
  await applyMigration(migration);
  await applyMigration(demoMigration);
});
