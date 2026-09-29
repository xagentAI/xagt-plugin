import { env } from "cloudflare:test";
import { beforeAll } from "vitest";
import migration from "../migrations/0001_initial.sql?raw";

beforeAll(async () => {
  const statements = migration
    .replace(/^PRAGMA[^;]+;/gm, "")
    .split(";")
    .map((statement) => statement.trim())
    .filter(Boolean)
    .map((statement) => env.DB.prepare(statement));
  await env.DB.batch(statements);
});
