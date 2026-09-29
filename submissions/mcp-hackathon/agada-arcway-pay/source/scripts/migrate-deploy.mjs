#!/usr/bin/env node
/**
 * `prisma migrate deploy`, wrapped in the same connection-retry discipline as
 * lib/prisma.ts.
 *
 * The schema engine runs as a separate process with its own connection, so the
 * client-side retry extension does not cover it. Against a Neon compute that
 * has scaled to zero, a cold `migrate deploy` fails with P1001 — during a
 * deploy that reads as a broken build rather than a sleeping database.
 *
 * Also strips `channel_binding` from the connection URLs. Neon includes it by
 * default and Prisma 6's connector rejects it, reporting the misleading
 * "Can't reach database server" rather than an unsupported-parameter error.
 */
import { spawnSync } from "node:child_process";
import { Socket } from "node:net";

const ATTEMPTS = 6;
const BACKOFF_MS = [500, 1500, 3000, 5000, 8000];

function sanitise(name) {
  const raw = process.env[name];
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.searchParams.has("channel_binding")) {
      url.searchParams.delete("channel_binding");
      console.log(`  [migrate-deploy] stripped channel_binding from ${name}`);
    }
    process.env[name] = url.toString();
    return url;
  } catch {
    return null;
  }
}

const direct = sanitise("DIRECT_URL");
sanitise("DATABASE_URL");

if (!process.env.DATABASE_URL) {
  console.error("  [migrate-deploy] DATABASE_URL is not set — cannot migrate.");
  process.exit(1);
}
if (!process.env.DIRECT_URL) {
  console.warn(
    "  [migrate-deploy] DIRECT_URL is not set. Migrations need an unpooled connection; " +
      "set it to Neon's direct (non-pooler) URL."
  );
}

/** Nudges the compute awake at the TCP level before the schema engine tries. */
function knock(url, timeoutMs = 5000) {
  return new Promise((resolve) => {
    if (!url) return resolve(false);
    const socket = new Socket();
    const done = (ok) => {
      socket.destroy();
      resolve(ok);
    };
    socket.setTimeout(timeoutMs);
    socket.once("connect", () => done(true));
    socket.once("timeout", () => done(false));
    socket.once("error", () => done(false));
    socket.connect(Number(url.port || 5432), url.hostname);
  });
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

for (let attempt = 1; attempt <= ATTEMPTS; attempt++) {
  await knock(direct);

  const result = spawnSync("prisma", ["migrate", "deploy"], {
    encoding: "utf8",
    env: process.env,
    shell: true,
  });
  const output = (result.stdout || "") + (result.stderr || "");

  if (result.status === 0) {
    if (attempt > 1) {
      console.log(`  [migrate-deploy] succeeded on attempt ${attempt}`);
    }
    process.stdout.write(output);
    process.exit(0);
  }

  const isConnectionError = /P1001|P1002|Can't reach database server/.test(output);
  if (!isConnectionError || attempt === ATTEMPTS) {
    // A real migration failure — a conflict, a bad SQL file — must fail the
    // build loudly rather than being retried into a timeout.
    process.stderr.write(output);
    console.error(
      isConnectionError
        ? `  [migrate-deploy] database unreachable after ${ATTEMPTS} attempts.`
        : "  [migrate-deploy] migration failed for a non-connection reason (see above)."
    );
    process.exit(result.status ?? 1);
  }

  const delay = BACKOFF_MS[attempt - 1] ?? 8000;
  console.warn(
    `  [migrate-deploy] database unreachable (cold start?) — retrying in ${delay}ms ` +
      `(attempt ${attempt + 1}/${ATTEMPTS})`
  );
  await sleep(delay);
}
