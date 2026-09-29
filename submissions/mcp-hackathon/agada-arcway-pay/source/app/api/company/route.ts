import { NextResponse } from "next/server";
import { AuthError, authErrorResponse, verifyIdentity } from "@/lib/auth";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/**
 * Completes employer signup: creates the Company and the User(EMPLOYER) that
 * administers it, in one transaction so a half-created account cannot exist.
 *
 * Refuses if this identity already has a User row, so the endpoint cannot be
 * replayed to spawn extra companies for the same person.
 */
export async function POST(request: Request) {
  try {
    const { privyUserId, email } = await verifyIdentity(request);

    if (!email) {
      throw new AuthError("This account has no email address linked.", 403);
    }

    let body: { name?: unknown };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const name = typeof body.name === "string" ? body.name.trim() : "";
    if (!name) {
      return NextResponse.json({ error: "A company name is required." }, { status: 400 });
    }
    if (name.length > 120) {
      return NextResponse.json({ error: "That company name is too long." }, { status: 400 });
    }

    const existing = await prisma.user.findUnique({ where: { privyUserId } });
    if (existing) {
      return NextResponse.json(
        { error: "This account is already set up." },
        { status: 409 }
      );
    }

    // A NESTED write, not an interactive transaction.
    //
    // This was `$transaction(async (tx) => ...)` with two sequential creates.
    // An interactive transaction holds a connection open across round trips
    // under a 5-second default, and on a cold Neon branch that budget is real
    // — worse here than elsewhere, because lib/prisma.ts retries a dropped
    // connection with 500ms + 1500ms of backoff, which can burn most of the
    // window from inside the transaction before the second write is even sent.
    //
    // A nested create is ONE statement, and Prisma already wraps nested writes
    // in their own transaction, so atomicity is unchanged: a company still
    // cannot exist without the user that administers it. If the unique
    // constraint on privyUserId loses a race, the whole write rolls back
    // exactly as it did before.
    const company = await prisma.company.create({
      data: {
        name,
        users: { create: { privyUserId, email, role: "EMPLOYER" } },
      },
    });

    return NextResponse.json(
      {
        status: "employer",
        role: "EMPLOYER",
        email,
        company: { id: company.id, name: company.name },
        destination: "/dashboard",
      },
      { status: 201 }
    );
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Company creation failed:", err);
    return NextResponse.json({ error: "Could not create company." }, { status: 500 });
  }
}
