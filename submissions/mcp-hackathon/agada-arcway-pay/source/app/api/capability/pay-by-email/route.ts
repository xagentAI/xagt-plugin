import { NextRequest, NextResponse } from "next/server";
import { provisionEmbeddedWallet } from "@/lib/privy";
import { createTransfer, getTransferStatus, isCircleConfigured } from "@/lib/circle";
import {
  createPayee,
  listPayees,
  openAgentPayout,
  updatePayeeStatus,
  updatePayoutStatus,
} from "@/lib/store";
import { prisma } from "@/lib/prisma";
import { authenticateApiKey, consumeRateLimit } from "@/lib/api-keys";

/**
 * pay-by-email — the agent-callable capability this hackathon submission
 * exposes (X-Agent AI MCP Hackathon 2026, General Challenge track).
 *
 * "AI agents are only as useful as the capabilities they can reliably call."
 * This is Arcway's core capability — provision a stablecoin-payable wallet
 * for someone identified only by an email address, then pay them in USDC —
 * exposed as a single, synchronous, agent-callable endpoint with an
 * unambiguous JSON input/output schema, independent of the human dashboard
 * (POST /api/payees + POST /api/payouts) that employers use.
 * Both entry points share the same underlying Privy + Circle logic in
 * lib/privy.ts and lib/circle.ts — this route is just a second, agent-facing
 * front door onto it, and every call here also lands in the same payee store
 * so it shows up in the human dashboard too.
 *
 * GET  -> returns this capability's machine-readable schema (what an agent,
 *         or a hackathon reviewer, needs to know to call it correctly).
 * POST -> executes one payment. Input: { payeeName, payeeEmail, amountUsdc }.
 *         Output: { status: "sent"|"failed"|"pending", walletAddress,
 *                    transferId, payeeId, errorMessage? }.
 */

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const SCHEMA = {
  name: "pay_by_email",
  description:
    "Pay a person or business a specified amount of USDC, identified only by their email address. If the recipient has no wallet, one is provisioned for them automatically (Privy embedded wallet) before the payment is sent — no wallet address, seed phrase, or prior crypto setup required from the recipient.",
  input_schema: {
    type: "object",
    required: ["payeeName", "payeeEmail", "amountUsdc"],
    properties: {
      payeeName: { type: "string", description: "Display name of the recipient." },
      payeeEmail: { type: "string", format: "email", description: "Recipient's email address. Used to look up or provision their embedded wallet." },
      amountUsdc: { type: "number", exclusiveMinimum: 0, description: "Amount to send, denominated in whole USDC (e.g. 25.5 = 25.50 USDC)." },
    },
  },
  output_schema: {
    type: "object",
    properties: {
      status: { type: "string", enum: ["sent", "failed", "pending"] },
      payeeId: { type: "string", description: "Internal id of the payee record created/updated by this call." },
      walletAddress: { type: "string", description: "The recipient's embedded wallet address that funds were sent to." },
      transferId: { type: "string", description: "Circle transfer id, if a transfer was created." },
      errorMessage: { type: "string", description: "Present only when status is \"failed\"." },
    },
  },
  example_request: {
    payeeName: "Ada Lovelace",
    payeeEmail: "ada@example.com",
    amountUsdc: 50,
  },
};

/**
 * The company that unauthenticated mock-mode calls write into.
 *
 * Resolved by a stable label rather than a hardcoded id, and never shared with
 * a signed-in employer's books. Only reachable when Circle is in mock mode, so
 * nothing it records corresponds to real money.
 */
const OPEN_DOOR_COMPANY_NAME = "Agent Sandbox (mock mode)";

async function resolveOpenDoorCompany() {
  const existing = await prisma.company.findFirst({
    where: { name: OPEN_DOOR_COMPANY_NAME },
  });
  return existing ?? prisma.company.create({ data: { name: OPEN_DOOR_COMPANY_NAME } });
}

export async function GET() {
  return NextResponse.json(SCHEMA);
}

/**
 * The generic body for any 500. Raw exception text never reaches the caller:
 * it carries internals — Prisma's messages include server file paths — and an
 * agent can do nothing useful with it. The detail is logged server-side instead.
 */
function internalError() {
  return NextResponse.json(
    { status: "failed", errorMessage: "Internal error." },
    { status: 500 }
  );
}

export async function POST(request: NextRequest) {
  // Last line of defence. The handler's own try only begins after auth, rate
  // limiting and validation, so a failure before it — a database error during
  // the key lookup, say — would otherwise escape as the framework's own 500.
  try {
    return await handlePost(request);
  } catch (err) {
    console.error("pay-by-email: unhandled error", err);
    return internalError();
  }
}

async function handlePost(request: NextRequest) {
  // AUTHENTICATION. This replaces the Phase 1 stopgap that refused outright in
  // live mode — that guard existed only because the endpoint had no way to
  // identify its caller, so anonymous access and a funded treasury could never
  // be allowed to coexist. A key resolves that: it names a company, and every
  // read and write below is scoped to it.
  //
  // TWO DOORS, both documented in SUBMISSION.md:
  //   - Live mode REQUIRES a key. Real money moves; callers must be named.
  //   - Mock mode stays open, so a reviewer with no credentials at all can
  //     still exercise the capability end to end.
  const auth = await authenticateApiKey(request);

  if (isCircleConfigured && !auth) {
    // Uniform 401: identical for absent, malformed, unknown and revoked keys.
    // Nothing here reveals whether a company or key exists.
    return NextResponse.json(
      {
        status: "failed",
        errorMessage:
          "A valid API key is required. Send it as: Authorization: Bearer ark_…",
      },
      { status: 401 }
    );
  }

  if (auth) {
    // Fails OPEN by design — see consumeRateLimit. A cold database must not
    // turn into a 503 for a reviewer.
    const limit = await consumeRateLimit(auth.keyId);
    if (!limit.allowed) {
      return NextResponse.json(
        {
          status: "failed",
          errorMessage: `Rate limit exceeded for this key (${limit.limit}/min). Retry in ${limit.retryAfterSeconds}s.`,
        },
        { status: 429, headers: { "Retry-After": String(limit.retryAfterSeconds) } }
      );
    }
  }

  let body: { payeeName?: unknown; payeeEmail?: unknown; amountUsdc?: unknown };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const payeeName = typeof body.payeeName === "string" ? body.payeeName.trim() : "";
  const payeeEmail = typeof body.payeeEmail === "string" ? body.payeeEmail.trim() : "";
  const amountUsdc = Number(body.amountUsdc);

  if (!payeeName) {
    return NextResponse.json({ error: "payeeName is required." }, { status: 400 });
  }
  if (!payeeEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(payeeEmail)) {
    return NextResponse.json({ error: "A valid payeeEmail is required." }, { status: 400 });
  }
  if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
    return NextResponse.json({ error: "amountUsdc must be a positive number." }, { status: 400 });
  }

  // Per-key ceiling. The public reviewer key sets one so that a key printed in
  // a submission document cannot drain the treasury in a single call.
  if (auth?.maxAmountUsdc != null && amountUsdc > auth.maxAmountUsdc) {
    return NextResponse.json(
      {
        status: "failed",
        errorMessage: `This key is limited to ${auth.maxAmountUsdc} USDC per payout.`,
      },
      { status: 403 }
    );
  }

  // Set once the ledger row exists, so the catch below can resolve it rather
  // than leaving a payout stranded at "pending" forever.
  let openPayoutId: string | null = null;
  let ledgerCompanyId: string | null = null;

  try {
    // 1. Provision (or reuse) the recipient's embedded wallet — no action
    //    required from them.
    const wallet = await provisionEmbeddedWallet(payeeEmail);

    // The company comes from the authenticated key. Unauthenticated calls only
    // reach here in mock mode, where they land in a dedicated open-door company
    // rather than any real tenant's books.
    const company = auth
      ? await prisma.company.findUniqueOrThrow({ where: { id: auth.companyId } })
      : await resolveOpenDoorCompany();
    ledgerCompanyId = company.id;

    // 2. Record the payee so this call shows up in the dashboard too,
    //    keeping both submission entry points backed by one shared system.
    const existing = (await listPayees(company.id)).find(
      (p) => p.email.toLowerCase() === payeeEmail.toLowerCase()
    );
    const payee = existing
      ? existing
      : await createPayee(
          company.id,
          { name: payeeName, email: payeeEmail, amountUsdc },
          wallet.address
        );

    // 2b. Open the ledger row. The payout row and the payee's "sending"
    //     status are written in ONE transaction (see openAgentPayout) and
    //     BEFORE the transfer — the same order and the same shape a dashboard
    //     run produces, so an agent payment appears in Activity, gets a run
    //     receipt, and reconciles in the payee's ledger like any other.
    const { payout } = await openAgentPayout(company.id, payee.id, amountUsdc);
    openPayoutId = payout.id;

    // 3. Execute the USDC transfer via Circle (Arc), then resolve its final
    //    state before responding, so a caller gets a definitive answer in
    //    one round trip.
    const created = await createTransfer({
      destinationAddress: wallet.address,
      amountUsdc,
    });

    if (created.status === "failed") {
      const reason = created.errorMessage ?? "Transfer creation failed.";
      await updatePayoutStatus(company.id, payout.id, "failed", { failureReason: reason });
      await updatePayeeStatus(company.id, payee.id, "failed", { failureReason: reason });
      return NextResponse.json(
        {
          status: "failed",
          payeeId: payee.id,
          walletAddress: wallet.address,
          errorMessage: reason,
        },
        { status: 502 }
      );
    }

    const final = await getTransferStatus(created.transferId);
    const status = final.status === "complete" ? "sent" : final.status === "failed" ? "failed" : "pending";

    const rowStatus = status === "sent" ? "sent" : status === "failed" ? "failed" : "sending";
    // Prefer the chain hash over Circle's internal id where we have one — it is
    // the thing a recipient can look up in an explorer. Matches the dashboard.
    // The API response below still returns Circle's transferId, unchanged.
    const reference = final.txHash ?? created.transferId;

    await updatePayoutStatus(company.id, payout.id, rowStatus, {
      transferId: reference,
      failureReason: final.errorMessage,
    });
    await updatePayeeStatus(company.id, payee.id, rowStatus, {
      transferId: reference,
      failureReason: final.errorMessage,
    });

    return NextResponse.json({
      status,
      payeeId: payee.id,
      walletAddress: wallet.address,
      transferId: created.transferId,
      errorMessage: final.errorMessage,
    });
  } catch (err) {
    console.error("pay-by-email capability failed:", err);
    if (openPayoutId && ledgerCompanyId) {
      // Best effort: if this write also fails there is nothing further to try,
      // and the original error is the one worth reporting.
      await updatePayoutStatus(ledgerCompanyId, openPayoutId, "failed", {
        failureReason: err instanceof Error ? err.message : "Unknown error.",
      }).catch(() => {});
    }
    return internalError();
  }
}
