#!/usr/bin/env node
/**
 * `prisma migrate dev`, retried around Neon cold starts.
 *
 * The schema engine runs as a separate process with its own connection, so
 * lib/prisma.ts's retry extension does not cover it. Against a compute that
 * has scaled to zero this fails with P1001 — observed needing six attempts in
 * practice, so a hand-run migration is otherwise a coin flip.
 *
 *   npm run db:migrate -- --name add_something
 */
import { spawnSync } from "node:child_process";
import { Socket } from "node:net";

const ATTEMPTS = 10;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function sanitise(name) {
  const raw = process.env[name];
  if (!raw) return null;
  try {
    const url = new URL(raw);
    url.searchParams.delete("channel_binding"); // Prisma 6 rejects it
    process.env[name] = url.toString();
    return url;
  } catch {
    return null;
  }
}

const direct = sanitise("DIRECT_URL");
sanitise("DATABASE_URL");

function knock(url, timeoutMs = 5000) {
  return new Promise((resolve) => {
    if (!url) return resolve(false);
    const socket = new Socket();
    const done = (ok) => { socket.destroy(); resolve(ok); };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
    socket.connect(Number(url.port || 5432), url.hostname);
  });
}

/**
 * A dev server started before a migration keeps the OLD generated Prisma
 * client in memory — `globalThis` caching in lib/prisma.ts means even a hot
 * reload will not pick up the new one. The result is a baffling
 * "Unknown argument `yourNewField`" at runtime while the schema, the database
 * and the generated types on disk are all correct. Warn loudly rather than
 * letting that be discovered from a stack trace.
 */
function warnIfDevServerRunning() {
  const ps = spawnSync("pgrep", ["-f", "next dev"], { encoding: "utf8" });
  const running = (ps.stdout || "").trim().split("\n").filter(Boolean);
  if (running.length === 0) return;
  console.warn(
    "\n  ⚠  A `next dev` server is running (pid " + running.join(", ") + ").\n" +
      "     It holds the previously generated Prisma client in memory, so new\n" +
      "     fields will read as `Unknown argument` until you RESTART it.\n" +
      "     Restart the dev server once this migration finishes.\n"
  );
}

warnIfDevServerRunning();

const passthrough = process.argv.slice(2);

for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
  await knock(direct);
  const result = spawnSync("prisma", ["migrate", "dev", ...passthrough], {
    encoding: "utf8", env: process.env, shell: true,
  });
  const output = (result.stdout || "") + (result.stderr || "");

  if (result.status === 0) {
    process.stdout.write(output);
    if (attempt > 1) console.log(`  [migrate-dev] succeeded on attempt ${attempt}`);
    process.exit(0);
  }

  const connectionError = /P1001|P1002|Can't reach database server/.test(output);
  if (!connectionError || attempt === ATTEMPTS) {
    process.stderr.write(output);
    process.exit(result.status ?? 1);
  }
  console.warn(`  [migrate-dev] unreachable (cold start?) — attempt ${attempt + 1}/${ATTEMPTS}`);
  await sleep(1500);
}
