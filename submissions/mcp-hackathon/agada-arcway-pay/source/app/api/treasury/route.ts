import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { getTreasuryBalance } from "@/lib/circle";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: Request) {
  try {
    // The balance is a company-level figure, so it needs the same guard as
    // the payee list even though today's mock value is constant.
    await requireEmployer(request);
    return NextResponse.json(await getTreasuryBalance());
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to read treasury balance:", err);
    return NextResponse.json({ error: "Could not load balance." }, { status: 500 });
  }
}
