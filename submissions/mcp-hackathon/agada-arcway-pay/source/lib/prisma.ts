import { Prisma, PrismaClient } from "@prisma/client";

/**
 * A single PrismaClient for the whole process, wrapped so that
 * connection-level failures are retried.
 *
 * WHY: Neon's free-tier compute scales to zero after a few minutes idle. The
 * first query after a quiet period can fail while the endpoint wakes, and
 * Prisma surfaces that as P1001 "Can't reach database server" — which reads
 * like a broken deployment rather than a cold start. That matters most for
 * GET/POST /api/capability/pay-by-email, which reviewers will hit cold after
 * days of inactivity; a single timeout there looks like a dead endpoint.
 *
 * WHAT IS AND ISN'T RETRIED: only failures to *reach* the database. A unique
 * constraint violation, a missing record, or a validation error is a real
 * answer and is passed straight through — retrying those would turn a clear
 * error into a slow one.
 */

/** Retried unconditionally: the query provably never reached the server. */
const NEVER_EXECUTED = new Set([
  "P1001", // Can't reach database server
  "P1002", // Database server timed out during connect
  "P2024", // Timed out fetching a new connection from the pool
]);

/**
 * Retried for reads only. These mean the connection dropped or timed out at
 * some point, so a write may or may not have landed — repeating it could
 * double-apply. Reads are safe to repeat; writes are not, so they surface.
 */
const AMBIGUOUS = new Set([
  "P1008", // Operations timed out
  "P1017", // Server has closed the connection
]);

const READ_OPERATIONS = new Set([
  "findUnique",
  "findUniqueOrThrow",
  "findFirst",
  "findFirstOrThrow",
  "findMany",
  "count",
  "aggregate",
  "groupBy",
  "$queryRaw",
  "$queryRawUnsafe",
]);

/** Backoff between attempts, in ms. Three attempts total. */
const BACKOFF_MS = [500, 1500];

function errorCode(err: unknown): string | undefined {
  // The two error classes spell the field differently: initialization errors
  // carry `errorCode`, known request errors carry `code`.
  if (err instanceof Prisma.PrismaClientInitializationError) return err.errorCode;
  if (err instanceof Prisma.PrismaClientKnownRequestError) return err.code;
  return undefined;
}

export function isRetryable(err: unknown, operation: string): boolean {
  const code = errorCode(err);
  if (!code) {
    // An initialization error without a code is still a failure to connect.
    return err instanceof Prisma.PrismaClientInitializationError;
  }
  if (NEVER_EXECUTED.has(code)) return true;
  if (AMBIGUOUS.has(code)) return READ_OPERATIONS.has(operation);
  return false;
}

/**
 * Runs `attempt`, retrying connection-level failures with backoff.
 *
 * Exported so the retry behaviour can be tested directly against injected
 * failures — a real Neon cold start is not reproducible on demand, and a test
 * that only proves "it eventually gives up" would miss the case that matters:
 * failing twice and then succeeding.
 */
export async function runWithRetry<T>(
  attempt: () => Promise<T>,
  label: string,
  operation: string
): Promise<T> {
  let lastError: unknown;

  for (let i = 0; i <= BACKOFF_MS.length; i++) {
    try {
      const result = await attempt();
      if (i > 0) {
        console.info(`[prisma-retry] ${label} succeeded on attempt ${i + 1}`);
      }
      return result;
    } catch (err) {
      lastError = err;
      if (i === BACKOFF_MS.length || !isRetryable(err, operation)) throw err;

      const delay = BACKOFF_MS[i];
      // Logged at warn so it is visible in production logs: how often this
      // fires is the signal for whether the compute needs to stop scaling
      // to zero.
      console.warn(
        `[prisma-retry] ${label} failed with ${
          errorCode(err) ?? "connection error"
        } — retrying in ${delay}ms (attempt ${i + 2}/${BACKOFF_MS.length + 1})`
      );
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  throw lastError;
}

function basePrisma(): PrismaClient {
  return new PrismaClient({
    log: process.env.NODE_ENV === "development" ? ["warn", "error"] : ["error"],
  });
}

function withRetry(client: PrismaClient) {
  return client.$extends({
    name: "neon-cold-start-retry",
    query: {
      async $allOperations({ model, operation, args, query }) {
        return runWithRetry(
          () => query(args),
          `${model ?? "raw"}.${operation}`,
          operation
        );
      },
    },
  });
}

type ExtendedPrismaClient = ReturnType<typeof withRetry>;

/**
 * Next.js's dev server hot-reloads modules on every edit; without this cache
 * each reload would construct another client and open another pool, and Neon
 * would start refusing connections.
 */
const globalForPrisma = globalThis as unknown as { prisma?: ExtendedPrismaClient };

export const prisma: ExtendedPrismaClient =
  globalForPrisma.prisma ?? withRetry(basePrisma());

if (process.env.NODE_ENV !== "production") {
  globalForPrisma.prisma = prisma;
}
