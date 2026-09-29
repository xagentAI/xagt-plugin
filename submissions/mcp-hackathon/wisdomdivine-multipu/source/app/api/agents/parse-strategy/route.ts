import { getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { assertTrustedOrigin } from "@/lib/request-security";
import { compilePromptToStrategy } from "@/lib/agents/strategy-compiler";
import { z } from "zod";

const parseSchema = z.object({
  prompt: z.string().min(3).max(1000),
});

export async function POST(request: Request) {
  const originError = assertTrustedOrigin(request);
  if (originError) {
    return Response.json({ error: originError }, { status: 403 });
  }

  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  try {
    const body = await request.json();
    const parsed = parseSchema.safeParse(body);

    if (!parsed.success) {
      return Response.json(
        { error: "Invalid prompt format", details: parsed.error.flatten() },
        { status: 400 }
      );
    }

    const compiled = compilePromptToStrategy(parsed.data.prompt);

    return Response.json({
      success: true,
      strategy: compiled,
      agentId: "agent_proto_" + Math.random().toString(36).substring(2, 9),
      compiledAt: new Date().toISOString(),
    });
  } catch (err: any) {
    console.error("[API] POST /api/agents/parse-strategy error:", err);
    return Response.json(
      { error: err.message || "Failed to compile strategy prompt" },
      { status: 500 }
    );
  }
}
