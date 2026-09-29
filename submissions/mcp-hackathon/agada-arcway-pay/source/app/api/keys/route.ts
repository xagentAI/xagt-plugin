import { NextResponse } from "next/server";
import { authErrorResponse, requireEmployer } from "@/lib/auth";
import { createApiKey } from "@/lib/api-keys";
import { prisma } from "@/lib/prisma";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

/** This company's keys. Never returns key material — there is none stored. */
export async function GET(request: Request) {
  try {
    const { company } = await requireEmployer(request);
    const keys = await prisma.apiKey.findMany({
      where: { companyId: company.id },
      orderBy: { createdAt: "desc" },
      select: {
        id: true,
        label: true,
        createdAt: true,
        lastUsedAt: true,
        revokedAt: true,
        rateLimitPerMinute: true,
        maxAmountUsdc: true,
      },
    });
    return NextResponse.json({
      keys: keys.map((k) => ({
        ...k,
        createdAt: k.createdAt.toISOString(),
        lastUsedAt: k.lastUsedAt?.toISOString() ?? null,
        revokedAt: k.revokedAt?.toISOString() ?? null,
        maxAmountUsdc: k.maxAmountUsdc ? k.maxAmountUsdc.toNumber() : null,
      })),
    });
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to list API keys:", err);
    return NextResponse.json({ error: "Could not load keys." }, { status: 500 });
  }
}

/** Creates a key. The raw value is in this response and nowhere else, ever. */
export async function POST(request: Request) {
  try {
    const { company } = await requireEmployer(request);

    let body: { label?: unknown };
    try {
      body = await request.json();
    } catch {
      return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
    }

    const label = typeof body.label === "string" ? body.label.trim() : "";
    if (!label) {
      return NextResponse.json({ error: "A label is required." }, { status: 400 });
    }

    const { id, raw } = await createApiKey(company.id, label);
    return NextResponse.json(
      {
        id,
        label,
        key: raw,
        warning: "This is the only time this key is shown. Store it now.",
      },
      { status: 201 }
    );
  } catch (err) {
    const res = authErrorResponse(err);
    if (res) return res;
    console.error("Failed to create API key:", err);
    return NextResponse.json({ error: "Could not create a key." }, { status: 500 });
  }
}
