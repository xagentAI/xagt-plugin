import { NextRequest, NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { provisionEmbeddedWallet } from "@/lib/privy";
import { createPayee, findPayeeByEmail, listPayees, requeuePayee } from "@/lib/store";
import type { NewPayeeInput } from "@/lib/types";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    const { company } = await requireEmployer(request);
    return NextResponse.json({ payees: await listPayees(company.id) });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to list payees:", err);
    return NextResponse.json({ error: "Could not load payees." }, { status: 500 });
  }
}

export async function POST(request: NextRequest) {
  let company;
  try {
    ({ company } = await requireEmployer(request));
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    throw err;
  }

  let body: Partial<NewPayeeInput>;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const name = body.name?.toString().trim();
  const email = body.email?.toString().trim();
  const amountUsdc = Number(body.amountUsdc);

  if (!name) {
    return NextResponse.json({ error: "Name is required." }, { status: 400 });
  }
  if (!email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
    return NextResponse.json({ error: "A valid email is required." }, { status: 400 });
  }
  if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
    return NextResponse.json(
      { error: "Amount must be a positive number." },
      { status: 400 }
    );
  }

  try {
    // Somebody already on this payroll is a repeat payment, not a new person:
    // reuse their row and wallet rather than erroring on the unique key or
    // making a pointless Privy call to re-provision a wallet they already have.
    const existing = await findPayeeByEmail(company.id, email);
    if (existing) {
      const payee = await requeuePayee(company.id, existing.id, amountUsdc);
      return NextResponse.json(
        { payee, requeued: true, walletMocked: false },
        { status: 200 }
      );
    }

    // Provision the payee's embedded wallet via Privy the moment they're
    // added — this is what lets us send them USDC before they've ever
    // opened the app or installed a wallet.
    const wallet = await provisionEmbeddedWallet(email);
    const payee = await createPayee(company.id, { name, email, amountUsdc }, wallet.address);
    return NextResponse.json({ payee, requeued: false, walletMocked: wallet.mocked }, { status: 201 });
  } catch (err) {
    console.error("Failed to create payee:", err);
    return NextResponse.json(
      { error: "Failed to provision an embedded wallet for this payee." },
      { status: 502 }
    );
  }
}
