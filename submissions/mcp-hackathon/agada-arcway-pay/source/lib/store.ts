import { Prisma } from "@prisma/client";
import { prisma } from "./prisma";
import type {
  NewPayeeInput,
  Payee,
  PayeeAccount,
  PayeeStatus,
  Payout,
  PersonNotification,
  ReceivedPayment,
  WithdrawalRecord,
} from "./types";

/**
 * Persistence layer — Postgres (Neon) via Prisma.
 *
 * This replaces the MVP JSON-file store. The exported function signatures are
 * unchanged from that version, so API routes and components did not need to
 * change when it was swapped.
 *
 * TWO CONVERSIONS happen here and nowhere else:
 *   - `Decimal` -> `number`. Money is stored as Decimal(20, 6) because USDC
 *     has 6 decimals and floats are the wrong tool for currency; the app's
 *     `Payee.amountUsdc` contract stays `number`.
 *   - `DateTime` -> ISO-8601 `string`, which is what the client components
 *     already expect.
 *
 * COMPANY SCOPING: every function here takes an explicit `companyId` and
 * filters on it. There is no ambient "current company" — callers must pass the
 * company resolved from the request's verified access token (lib/auth.ts), so
 * a route physically cannot read another tenant's rows by forgetting a filter.
 *
 * Update and delete paths scope by `{ id, companyId }` rather than `{ id }`
 * alone: knowing another company's payee id must not be enough to write to it.
 */

type PayeeRow = Prisma.PayeeGetPayload<Record<string, never>>;
type PayoutRow = Prisma.PayoutGetPayload<{ include: { payee: true } }>;

function toPayee(row: PayeeRow): Payee {
  return {
    id: row.id,
    name: row.name,
    email: row.email,
    amountUsdc: row.amountUsdc.toNumber(),
    walletAddress: row.walletAddress,
    privyUserId: row.privyUserId ?? undefined,
    status: row.status,
    transferId: row.transferId ?? undefined,
    failureReason: row.failureReason ?? undefined,
    createdAt: row.createdAt.toISOString(),
    updatedAt: row.updatedAt.toISOString(),
  };
}

function toPayout(row: PayoutRow): Payout {
  return {
    id: row.id,
    runId: row.runId,
    payeeId: row.payeeId,
    payeeName: row.payee.name,
    payeeEmail: row.payee.email,
    walletAddress: row.payee.walletAddress,
    claimed: row.payee.privyUserId != null,
    amountUsdc: row.amountUsdc.toNumber(),
    status: row.status,
    transferId: row.transferId ?? undefined,
    failureReason: row.failureReason ?? undefined,
    createdAt: row.createdAt.toISOString(),
    sentAt: row.sentAt?.toISOString(),
    notifyStatus: row.notifyStatus,
    notifyError: row.notifyError ?? undefined,
    notifiedAt: row.notifiedAt?.toISOString(),
    lastNotifyAttemptAt: row.lastNotifyAttemptAt?.toISOString(),
    notifyAttempts: row.notifyAttempts,
  };
}

export async function listPayees(companyId: string): Promise<Payee[]> {
  const rows = await prisma.payee.findMany({
    where: { companyId },
    // Newest first, so a freshly-added payee shows up at the top of the table.
    orderBy: { createdAt: "desc" },
  });
  return rows.map(toPayee);
}

/**
 * Adds a payee, or updates the standing amount and name if that email is
 * already on this company's list.
 *
 * The upsert exists because (companyId, email) is unique: the same person
 * cannot appear twice on one company's payroll. Re-adding them is read as
 * "change what they're owed", which is what the dashboard's add form should
 * do. Their wallet address is never reassigned once provisioned.
 */
export async function createPayee(
  companyId: string,
  input: NewPayeeInput,
  walletAddress: string
): Promise<Payee> {
  const email = input.email.trim().toLowerCase();

  const row = await prisma.payee.upsert({
    where: { companyId_email: { companyId, email } },
    update: {
      name: input.name.trim(),
      amountUsdc: new Prisma.Decimal(input.amountUsdc),
      status: "pending",
    },
    create: {
      companyId,
      name: input.name.trim(),
      email,
      amountUsdc: new Prisma.Decimal(input.amountUsdc),
      walletAddress,
      status: "pending",
    },
  });
  return toPayee(row);
}

/**
 * Queues an existing payee for another payment.
 *
 * Reuses the row and its wallet address: the person already has a wallet, so
 * re-provisioning would be a pointless Privy call, and creating a second row
 * would violate the (companyId, email) unique key and split their history in
 * two. Scoped by company so one tenant cannot queue another's payee.
 */
export async function requeuePayee(
  companyId: string,
  payeeId: string,
  amountUsdc: number
): Promise<Payee | null> {
  try {
    const row = await prisma.payee.update({
      where: { id: payeeId, companyId },
      data: {
        amountUsdc: new Prisma.Decimal(amountUsdc),
        status: "pending",
        // A fresh run should not inherit the last one's failure text.
        failureReason: null,
        transferId: null,
      },
    });
    return toPayee(row);
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2025") {
      return null;
    }
    throw err;
  }
}

/** Looks up a payee by email within one company, for the add-vs-requeue decision. */
export async function findPayeeByEmail(
  companyId: string,
  email: string
): Promise<Payee | null> {
  const row = await prisma.payee.findUnique({
    where: { companyId_email: { companyId, email: email.trim().toLowerCase() } },
  });
  return row ? toPayee(row) : null;
}

export async function updatePayeeStatus(
  companyId: string,
  id: string,
  status: PayeeStatus,
  extra: Partial<Pick<Payee, "transferId" | "failureReason">> = {}
): Promise<Payee | null> {
  try {
    const row = await prisma.payee.update({
      // Scoped by company: an id alone must not grant write access.
      where: { id, companyId },
      data: {
        status,
        ...(extra.transferId !== undefined ? { transferId: extra.transferId } : {}),
        // An explicit undefined must still clear a stale reason on retry.
        failureReason: extra.failureReason ?? null,
      },
    });
    return toPayee(row);
  } catch (err) {
    // P2025 = record not found, which the JSON store signalled with null.
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2025") {
      return null;
    }
    throw err;
  }
}

export async function getPayee(companyId: string, id: string): Promise<Payee | null> {
  const row = await prisma.payee.findFirst({ where: { id, companyId } });
  return row ? toPayee(row) : null;
}

/* ------------------------------------------------------------ payouts --- */

/**
 * Opens a ledger row for one recipient in one run. Called once per recipient
 * at the moment a run is confirmed, before any transfer is attempted, so a
 * crash mid-run still leaves a record of what was intended.
 */
/** Opens a run. Payouts are written against the id this returns. */
export async function createPayoutRun(companyId: string): Promise<string> {
  const run = await prisma.payoutRun.create({
    data: { companyId },
    select: { id: true },
  });
  return run.id;
}

export async function createPayout(
  companyId: string,
  runId: string,
  payeeId: string,
  amountUsdc: number
): Promise<Payout> {
  const row = await prisma.payout.create({
    data: {
      companyId,
      runId,
      payeeId,
      amountUsdc: new Prisma.Decimal(amountUsdc),
      status: "pending",
    },
    include: { payee: true },
  });
  return toPayout(row);
}

/**
 * Records an agent-initiated payment exactly the way the dashboard records a
 * human one — a run, a payout row inside it, and the payee moved to "sending"
 * — in a single transaction.
 *
 * WHY A TRANSACTION: the payee's status and the ledger row are two halves of
 * one fact. Written separately, a failure between them leaves a payee marked
 * "sending" with no payout behind it (a payment that reconciles to nothing) or
 * a payout row for a payee that never left "pending". Neither is recoverable
 * by inspection after the fact.
 *
 * WHY A RUN OF ONE: `Payout.runId` is required, deliberately — a payout
 * outside a run is a payment nobody authorised. One call to the capability
 * endpoint IS one authorisation, so it maps cleanly onto a single-payout run,
 * and the receipt screen renders it with no special case. The alternative,
 * making `runId` nullable, would force every receipt, run query and reconcile
 * path to handle a runless payout in exchange for nothing.
 *
 * WHY BEFORE THE TRANSFER: same order as app/api/payouts/route.ts. A crash
 * between here and the broadcast leaves a record of what was intended; the
 * reverse order can move money with nothing to show for it.
 *
 * Note there is no fee recorded here, because a dashboard payout records none
 * either: on the employer -> payee leg gas is paid by the Circle treasury and
 * is not itemised per recipient. `feeUsdc` belongs to `Withdrawal`, the
 * payee-side leg, where the fee leaves the payee's own balance.
 */
export async function openAgentPayout(
  companyId: string,
  payeeId: string,
  amountUsdc: number
): Promise<{ runId: string; payout: Payout }> {
  // Two statements, not three, and a BATCH transaction rather than an
  // interactive one.
  //
  // The obvious shape here is `$transaction(async (tx) => ...)` with three
  // sequential awaits. It works locally and fails in production: an
  // interactive transaction holds a connection open across round trips under a
  // 5-second default timeout, and against a cold Neon branch three round trips
  // routinely exceed it — which aborts the transaction and 500s a payment that
  // was otherwise fine. Observed, not theorised.
  //
  // The array form sends both statements in one batch, so there is no
  // round-trip budget to blow, and nesting the payout inside the run's create
  // collapses what would be two statements into one.
  const [run] = await prisma.$transaction([
    prisma.payoutRun.create({
      data: {
        companyId,
        payouts: {
          create: {
            companyId,
            payeeId,
            amountUsdc: new Prisma.Decimal(amountUsdc),
            status: "pending",
          },
        },
      },
      include: { payouts: { include: { payee: true } } },
    }),
    prisma.payee.update({
      // Scoped by company, like every other write in this file.
      where: { id: payeeId, companyId },
      data: {
        status: "sending",
        // A repeat payment must not inherit the last attempt's failure text.
        failureReason: null,
      },
    }),
  ]);

  return { runId: run.id, payout: toPayout(run.payouts[0]) };
}

export async function updatePayoutStatus(
  companyId: string,
  id: string,
  status: PayeeStatus,
  extra: { transferId?: string; failureReason?: string } = {}
): Promise<Payout | null> {
  try {
    const row = await prisma.payout.update({
      where: { id, companyId },
      data: {
        status,
        ...(extra.transferId !== undefined ? { transferId: extra.transferId } : {}),
        failureReason: extra.failureReason ?? null,
        // Stamped when the transfer reaches a terminal state, so a receipt can
        // show when the money actually landed.
        ...(status === "sent" || status === "failed" ? { sentAt: new Date() } : {}),
      },
      include: { payee: true },
    });
    return toPayout(row);
  } catch (err) {
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2025") {
      return null;
    }
    throw err;
  }
}

/** Every payout ever recorded for this company, newest first. */
export async function listPayouts(companyId: string, limit = 100): Promise<Payout[]> {
  const rows = await prisma.payout.findMany({
    where: { companyId },
    include: { payee: true },
    orderBy: { createdAt: "desc" },
    take: limit,
  });
  return rows.map(toPayout);
}

/** The payouts written by one run, identified by the ids returned when it ran. */
export async function listPayoutsByIds(companyId: string, ids: string[]): Promise<Payout[]> {
  if (ids.length === 0) return [];
  const rows = await prisma.payout.findMany({
    where: { id: { in: ids }, companyId },
    include: { payee: true },
    orderBy: { createdAt: "asc" },
  });
  return rows.map(toPayout);
}

/* ------------------------------------------------ the payee's own view --- */

/**
 * PERSON-SCOPED QUERIES. Everything above this line is scoped to one company,
 * because an employer must never see another employer's books. Everything
 * below deliberately does the OPPOSITE: it unions across every company that
 * has ever paid this person.
 *
 * A contractor with two clients has two `Payee` rows under two different
 * companies. On /claim they are one person with one wallet, and must see both
 * — scoping these by a single companyId would silently hide half their money.
 *
 * Identity resolves by `privyUserId` first (set when they claim their wallet)
 * and falls back to `email`, which is what links rows created before they ever
 * signed in.
 */
function personWhere(privyUserId: string, email: string | null) {
  const clauses: Prisma.PayeeWhereInput[] = [{ privyUserId }];
  if (email) clauses.push({ email: email.toLowerCase() });
  return { OR: clauses };
}

/** Every payee row belonging to this person, across all companies. */
export async function listAccountsForPerson(
  privyUserId: string,
  email: string | null
): Promise<PayeeAccount[]> {
  const rows = await prisma.payee.findMany({
    where: personWhere(privyUserId, email),
    include: { company: true },
    orderBy: { createdAt: "desc" },
  });

  return rows.map((row) => ({
    payeeId: row.id,
    companyName: row.company.name,
    amountUsdc: row.amountUsdc.toNumber(),
    walletAddress: row.walletAddress,
    status: row.status,
  }));
}

/** Every payment this person has received, from any company, newest first. */
export async function listPaymentsForPerson(
  privyUserId: string,
  email: string | null
): Promise<ReceivedPayment[]> {
  const rows = await prisma.payout.findMany({
    where: { payee: personWhere(privyUserId, email) },
    include: { company: true },
    orderBy: { createdAt: "desc" },
  });

  return rows.map((row) => ({
    id: row.id,
    companyName: row.company.name,
    amountUsdc: row.amountUsdc.toNumber(),
    status: row.status,
    transferId: row.transferId ?? undefined,
    createdAt: row.createdAt.toISOString(),
    sentAt: row.sentAt?.toISOString(),
  }));
}

/**
 * Marks every payee row for this email as claimed by this Privy identity —
 * across all companies, because claiming a wallet is something the person
 * does once, not once per employer.
 */
export async function claimPayeeRows(
  privyUserId: string,
  email: string
): Promise<number> {
  const { count } = await prisma.payee.updateMany({
    where: { email: email.toLowerCase(), privyUserId: null },
    data: { privyUserId },
  });
  return count;
}

/**
 * Withdrawals are person-scoped like everything else in this section: a payee
 * with two employers has one wallet and one withdrawal history.
 */
export async function listWithdrawalsForPerson(
  privyUserId: string,
  email: string | null
): Promise<WithdrawalRecord[]> {
  const rows = await prisma.withdrawal.findMany({
    where: { payee: personWhere(privyUserId, email) },
    orderBy: { createdAt: "desc" },
  });

  return rows.map((row) => ({
    id: row.id,
    amountUsdc: row.amountUsdc.toNumber(),
    feeUsdc: row.feeUsdc.toNumber(),
    destinationAddress: row.destinationAddress,
    status: row.status,
    txHash: row.txHash ?? undefined,
    failureReason: row.failureReason ?? undefined,
    createdAt: row.createdAt.toISOString(),
    sentAt: row.sentAt?.toISOString(),
    // A mock hash is prefixed so it can never be mistaken for a real one.
    simulated: (row.txHash ?? "").startsWith("0xmock"),
  }));
}

/**
 * Total already withdrawn, INCLUDING network fees — what the ledger-derived
 * balance subtracts.
 *
 * The fee leaves the wallet just as the amount does, so omitting it made the
 * balance card disagree with the running balance in the activity list by
 * exactly the fees paid. Both now compute the same thing.
 */
export async function sumWithdrawnForPerson(
  privyUserId: string,
  email: string | null
): Promise<number> {
  const rows = await prisma.withdrawal.findMany({
    where: { payee: personWhere(privyUserId, email), status: "sent" },
    select: { amountUsdc: true, feeUsdc: true },
  });
  return rows.reduce(
    (sum, r) => sum + r.amountUsdc.toNumber() + r.feeUsdc.toNumber(),
    0
  );
}

/**
 * Records a withdrawal that has ALREADY been broadcast, keyed on its
 * transaction hash.
 *
 * Idempotent by design: the browser broadcasts first and posts the hash
 * second, so a client retry after a dropped response must not create a second
 * row. The hash is the natural identity — the chain already assigned it.
 */
export async function recordBroadcastWithdrawal(input: {
  payeeId: string;
  amountUsdc: number;
  feeUsdc: number;
  destinationAddress: string;
  txHash: string;
}): Promise<{ withdrawal: WithdrawalRecord; created: boolean }> {
  const existing = await prisma.withdrawal.findFirst({
    where: { txHash: input.txHash },
  });
  if (existing) {
    return { withdrawal: toWithdrawalRecord(existing), created: false };
  }

  try {
    const row = await prisma.withdrawal.create({
      data: {
        payeeId: input.payeeId,
        amountUsdc: new Prisma.Decimal(input.amountUsdc),
        feeUsdc: new Prisma.Decimal(input.feeUsdc),
        destinationAddress: input.destinationAddress,
        txHash: input.txHash,
        status: "sending",
      },
    });
    return { withdrawal: toWithdrawalRecord(row), created: true };
  } catch (err) {
    // Two retries racing: whoever lost re-reads the row the other wrote.
    if (err instanceof Prisma.PrismaClientKnownRequestError && err.code === "P2002") {
      const row = await prisma.withdrawal.findFirst({ where: { txHash: input.txHash } });
      if (row) return { withdrawal: toWithdrawalRecord(row), created: false };
    }
    throw err;
  }
}

type WithdrawalRow = Prisma.WithdrawalGetPayload<Record<string, never>>;

function toWithdrawalRecord(row: WithdrawalRow): WithdrawalRecord {
  return {
    id: row.id,
    amountUsdc: row.amountUsdc.toNumber(),
    feeUsdc: row.feeUsdc.toNumber(),
    destinationAddress: row.destinationAddress,
    status: row.status,
    txHash: row.txHash ?? undefined,
    failureReason: row.failureReason ?? undefined,
    createdAt: row.createdAt.toISOString(),
    sentAt: row.sentAt?.toISOString(),
    simulated: (row.txHash ?? "").startsWith("0xmock"),
  };
}

/** One withdrawal by hash, scoped to the person — for the settle poll. */
export async function getWithdrawalByHash(
  privyUserId: string,
  email: string | null,
  txHash: string
): Promise<WithdrawalRecord | null> {
  const row = await prisma.withdrawal.findFirst({
    where: { txHash, payee: personWhere(privyUserId, email) },
  });
  return row ? toWithdrawalRecord(row) : null;
}

export async function createWithdrawal(
  payeeId: string,
  amountUsdc: number,
  feeUsdc: number,
  destinationAddress: string
): Promise<string> {
  const row = await prisma.withdrawal.create({
    data: {
      payeeId,
      amountUsdc: new Prisma.Decimal(amountUsdc),
      feeUsdc: new Prisma.Decimal(feeUsdc),
      destinationAddress,
      status: "pending",
    },
    select: { id: true },
  });
  return row.id;
}

/**
 * One withdrawal, scoped to the person who made it. A withdrawal id from
 * somebody else's account resolves to nothing rather than leaking a receipt.
 */
export async function getWithdrawalForPerson(
  privyUserId: string,
  email: string | null,
  id: string
): Promise<WithdrawalRecord | null> {
  const row = await prisma.withdrawal.findFirst({
    where: { id, payee: personWhere(privyUserId, email) },
  });
  if (!row) return null;
  return {
    id: row.id,
    amountUsdc: row.amountUsdc.toNumber(),
    feeUsdc: row.feeUsdc.toNumber(),
    destinationAddress: row.destinationAddress,
    status: row.status,
    txHash: row.txHash ?? undefined,
    failureReason: row.failureReason ?? undefined,
    createdAt: row.createdAt.toISOString(),
    sentAt: row.sentAt?.toISOString(),
    simulated: (row.txHash ?? "").startsWith("0xmock"),
  };
}

export async function settleWithdrawal(
  id: string,
  status: PayeeStatus,
  extra: { txHash?: string; failureReason?: string } = {}
): Promise<void> {
  await prisma.withdrawal.update({
    where: { id },
    data: {
      status,
      txHash: extra.txHash,
      failureReason: extra.failureReason ?? null,
      ...(status === "sent" || status === "failed" ? { sentAt: new Date() } : {}),
    },
  });
}

/**
 * Every payout in one run, by run id.
 *
 * Membership is recorded on the row, not inferred from creation time. The
 * previous version grouped payouts written within 15 seconds of each other,
 * which was exact locally but would silently split one slow run in two — or
 * merge two quick ones — once cold starts and real Circle latency were in
 * play, producing a receipt that looked fine and was wrong.
 *
 * Scoped by company, so another tenant's run id returns nothing.
 */
export async function listPayoutsInRun(
  companyId: string,
  runId: string
): Promise<Payout[]> {
  const rows = await prisma.payout.findMany({
    where: { runId, companyId },
    include: { payee: true },
    orderBy: { createdAt: "asc" },
  });
  return rows.map(toPayout);
}

/**
 * Payees with the notification state of their most recent payout.
 *
 * This is what the People page shows when someone says "I never got it" — the
 * employer needs the last send time and a way to try again, without hunting
 * for the run it belonged to.
 */
export async function listPeopleWithNotifications(
  companyId: string
): Promise<PersonNotification[]> {
  const rows = await prisma.payee.findMany({
    where: { companyId },
    orderBy: { createdAt: "desc" },
    include: {
      payouts: {
        orderBy: { createdAt: "desc" },
        take: 1,
      },
    },
  });

  return rows.map((row) => {
    const latest = row.payouts[0];
    return {
      payee: toPayee(row),
      latestPayout: latest
        ? {
            id: latest.id,
            runId: latest.runId,
            amountUsdc: latest.amountUsdc.toNumber(),
            status: latest.status,
            notifyStatus: latest.notifyStatus,
            notifiedAt: latest.notifiedAt?.toISOString(),
            lastNotifyAttemptAt: latest.lastNotifyAttemptAt?.toISOString(),
            notifyAttempts: latest.notifyAttempts,
            notifyError: latest.notifyError ?? undefined,
          }
        : undefined,
    };
  });
}
