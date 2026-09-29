/**
 * Process-wide PostgreSQL pool and Drizzle client. Created lazily on first
 * use, once per process (the pool is parked on `globalThis` so Next.js dev
 * hot-reloads do not leak connections). Uses the Neon pooled `DATABASE_URL`;
 * migrations use the unpooled URL through `drizzle.config.ts`, never here.
 */
import "server-only";

import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "./schema";

export type Database = NodePgDatabase<typeof schema>;

export interface DatabaseHandle {
  readonly db: Database;
  readonly pool: Pool;
}

const globalHandle = globalThis as typeof globalThis & { __settleDatabase?: DatabaseHandle };

export function createDatabase(connectionString: string): DatabaseHandle {
  const pool = new Pool({
    connectionString,
    max: 5,
    idleTimeoutMillis: 30_000,
    connectionTimeoutMillis: 10_000,
  });
  return { db: drizzle(pool, { schema }), pool };
}

/** Returns the shared database handle, creating it on first call. */
export function getDatabase(connectionString: string): DatabaseHandle {
  globalHandle.__settleDatabase ??= createDatabase(connectionString);
  return globalHandle.__settleDatabase;
}
