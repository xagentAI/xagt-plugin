import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { listPayoutsInRun } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * One past run's receipt, addressed by its PayoutRun id. Scoped to the
 * caller's company, so a run id from another tenant resolves to nothing
 * rather than leaking rows.
 */
export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { company } = await requireEmployer(request);
    const { id } = await params;

    const payouts = await listPayoutsInRun(company.id, id);
    if (payouts.length === 0) {
      return NextResponse.json({ error: "No such run." }, { status: 404 });
    }

    return NextResponse.json({ payouts });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to load run:", err);
    return NextResponse.json({ error: "Could not load that run." }, { status: 500 });
  }
}
