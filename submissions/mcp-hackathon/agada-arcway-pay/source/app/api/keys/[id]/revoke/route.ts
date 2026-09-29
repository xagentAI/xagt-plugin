import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Revokes a key. Scoped {id, companyId} so one tenant cannot revoke another's,
 * and idempotent — revoking twice is not an error.
 */
export async function POST(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  try {
    const { company } = await requireEmployer(request);
    const { id } = await params;

    const owned = await prisma.apiKey.findFirst({
      where: { id, companyId: company.id },
      select: { id: true, revokedAt: true },
    });
    if (!owned) {
      return NextResponse.json({ error: "No such key." }, { status: 404 });
    }

    if (!owned.revokedAt) {
      await prisma.apiKey.update({
        where: { id: owned.id },
        data: { revokedAt: new Date() },
      });
    }

    return NextResponse.json({ id: owned.id, revoked: true });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to revoke API key:", err);
    return NextResponse.json({ error: "Could not revoke that key." }, { status: 500 });
  }
}
