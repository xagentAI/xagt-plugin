import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { requeuePayee } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Queues an existing payee for another payment.
 *
 * The wallet already exists, so nothing is provisioned and no row is created —
 * paying someone a second time is a change of amount and status on the row
 * that already holds their history.
 */
export async function POST(request: Request) {
  try {
    const { company } = await requireEmployer(request);

    let body: { payeeId?: unknown; amountUsdc?: unknown };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const payeeId = typeof body.payeeId === "string" ? body.payeeId : "";
    const amountUsdc = Number(body.amountUsdc);

    if (!payeeId) {
      return NextResponse.json({ error: "payeeId is required." }, { status: 400 });
    }
    if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
      return NextResponse.json(
        { error: "Enter an amount greater than zero." },
        { status: 400 }
      );
    }

    const payee = await requeuePayee(company.id, payeeId, amountUsdc);
    if (!payee) {
      return NextResponse.json({ error: "No such payee." }, { status: 404 });
    }

    return NextResponse.json({ payee });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Requeue failed:", err);
    return NextResponse.json({ error: "Could not queue that payment." }, { status: 500 });
  }
}
