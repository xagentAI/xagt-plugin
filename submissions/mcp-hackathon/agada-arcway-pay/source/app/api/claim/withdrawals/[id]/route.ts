import { NextResponse } from "next/server";
import { authErrorResponse, requirePayee } from "@/lib/auth";
import { getWithdrawalForPerson } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** One withdrawal receipt, scoped to the person who made it. */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { privyUserId, email } = await requirePayee(request);
    const { id } = await params;

    const withdrawal = await getWithdrawalForPerson(privyUserId, email, id);
    if (!withdrawal) {
      return NextResponse.json({ error: "No such withdrawal." }, { status: 404 });
    }

    return NextResponse.json({ withdrawal });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to load withdrawal:", err);
    return NextResponse.json({ error: "Could not load that receipt." }, { status: 500 });
  }
}
