#!/usr/bin/env node
/**
 * Runs a command with .env.local loaded into the environment.
 *
 * Prisma's CLI reads `.env`, but this project keeps its secrets in
 * `.env.local` — the file Next.js loads, and deliberately the only one, so
 * credentials can't drift between two copies. Rather than duplicate
 * DATABASE_URL/DIRECT_URL into a second file, CLI commands that need them go
 * through this wrapper:
 *
 *   node scripts/with-env.mjs prisma migrate dev
 *
 * Deliberately dependency-free. Real environment variables always win, so
 * CI and Vercel (which inject their own) are unaffected.
 */
import { spawn } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

const envPath = path.join(process.cwd(), ".env.local");

try {
  const raw = readFileSync(envPath, "utf8");
  for (const line of raw.split("\n")) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (!m) continue;
    let [, key, value] = m;
    // Strip matched surrounding quotes, if present.
    const q = value[0];
    if ((q === '"' || q === "'") && value.at(-1) === q) value = value.slice(1, -1);
    if (process.env[key] === undefined) process.env[key] = value;
  }
} catch (err) {
  if (err.code !== "ENOENT") throw err;
  // No .env.local (CI, production) — rely on the real environment.
}

const [cmd, ...args] = process.argv.slice(2);
if (!cmd) {
  console.error("usage: node scripts/with-env.mjs <command> [args...]");
  process.exit(2);
}

spawn(cmd, args, { stdio: "inherit", env: process.env, shell: process.platform === "win32" })
  .on("exit", (code) => process.exit(code ?? 1));
