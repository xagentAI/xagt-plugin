#!/usr/bin/env node
/**
 * Wipes every application row, leaving the schema and migration history
 * intact. This is a data wipe, not a reset: `prisma migrate reset` would drop
 * and rebuild the schema, which is a much bigger hammer than "empty the
 * tables".
 *
 * Deletion order is the reverse of the dependency graph. Cascades would cover
 * most of it, but doing it explicitly means the row counts printed below are
 * the truth about what this script removed rather than what the database
 * silently removed on its behalf.
 *
 *   Withdrawal -> Payee
 *   Payout     -> Payee, Company, PayoutRun
 *   PayoutRun  -> Company
 *   Payee      -> Company
 *   User       -> Company
 *   Company
 *
 * Run with:  npm run db:clean
 */
import { PrismaClient } from "@prisma/client";

/**
 * Admin work goes over the DIRECT (unpooled) endpoint, for the same reason
 * migrations do: the pooler adds a layer that is unhelpful for a short-lived
 * maintenance connection, and Neon's wake-from-idle is noticeably flakier
 * through it.
 */
const prisma = new PrismaClient({
  datasources: { db: { url: process.env.DIRECT_URL ?? process.env.DATABASE_URL } },
});

// Order matters: Payout references PayoutRun, so runs are cleared after the
// payouts that point at them and before the companies that own them.
const TABLES = ["withdrawal", "payout", "payoutRun", "payee", "user", "company"];

/**
 * Neon scales computes to zero, so the first connection after an idle period
 * can time out while the endpoint wakes. Prisma reports that as P1001
 * ("Can't reach database server"), which reads like a misconfiguration but
 * usually just means "not awake yet" — so wake it deliberately before doing
 * any real work.
 */
async function wake(attempts = 8) {
  for (let i = 1; i <= attempts; i++) {
    try {
      await prisma.$queryRaw`select 1`;
      // One real table read too: `select 1` can succeed a moment before the
      // compute will serve model queries.
      await prisma.company.count();
      return;
    } catch (err) {
      if (i === attempts) throw err;
      console.log(`  database not awake yet (attempt ${i}/${attempts}) — retrying…`);
      await new Promise((r) => setTimeout(r, 2500));
    }
  }
}

// Sequential rather than parallel: a freshly-woken Neon compute handles one
// connection at a time far more reliably than five at once.
async function counts() {
  const out = {};
  for (const t of TABLES) out[t] = await prisma[t].count();
  return out;
}

function print(label, rows) {
  console.log(`\n  ${label}`);
  for (const [table, n] of Object.entries(rows)) {
    console.log(`    ${table.padEnd(12)} ${String(n).padStart(5)}`);
  }
  const total = Object.values(rows).reduce((a, b) => a + b, 0);
  console.log(`    ${"TOTAL".padEnd(12)} ${String(total).padStart(5)}`);
}

try {
  await wake();
} catch (err) {
  console.error(`\n  Could not reach the database: ${err.message.split("\n")[0]}\n`);
  await prisma.$disconnect();
  process.exit(1);
}

const before = await counts();
print("BEFORE", before);

// FK-safe order: children first, parents last.
for (const table of TABLES) {
  const { count } = await prisma[table].deleteMany({});
  console.log(`\n  deleted ${String(count).padStart(5)} from ${table}`);
}

const after = await counts();
print("AFTER", after);

const remaining = Object.values(after).reduce((a, b) => a + b, 0);
console.log(
  remaining === 0
    ? "\n  Database is empty. Schema and migrations untouched.\n"
    : `\n  WARNING: ${remaining} row(s) remain.\n`
);

await prisma.$disconnect();
process.exit(remaining === 0 ? 0 : 1);
