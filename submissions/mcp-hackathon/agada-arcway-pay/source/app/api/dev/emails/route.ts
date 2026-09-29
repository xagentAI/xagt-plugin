import { NextResponse } from "next/server";
import { isEmailConfigured, listMockEmails } from "@/lib/email";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * The mock outbox. DEV ONLY — it exposes rendered message bodies, so it is
 * refused outright in production rather than merely hidden.
 */
export async function GET() {
  if (process.env.NODE_ENV === "production") {
    return NextResponse.json({ error: "Not available in production." }, { status: 404 });
  }
  return NextResponse.json({
    emails: await listMockEmails(),
    live: isEmailConfigured,
  });
}
