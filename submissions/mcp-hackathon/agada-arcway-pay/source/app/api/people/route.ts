import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { listPeopleWithNotifications } from "@/lib/store";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** The People directory, with each payee's latest notification state. */
export async function GET(request: Request) {
  try {
    const { company } = await requireEmployer(request);
    return NextResponse.json({ people: await listPeopleWithNotifications(company.id) });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to list people:", err);
    return NextResponse.json({ error: "Could not load people." }, { status: 500 });
  }
}
