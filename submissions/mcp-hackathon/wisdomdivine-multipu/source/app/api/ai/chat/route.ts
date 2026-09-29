import { getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { assertTrustedOrigin } from "@/lib/request-security";
import { streamGroqChat, ChatMessage } from "@/lib/ai/groq";
import { fetchOlaXbtSignals, OlaXbtStrategySignal } from "@/lib/olaxbt/client";
import { compilePromptToStrategy } from "@/lib/agents/strategy-compiler";
import { createAdminSupabase } from "@/lib/supabase/server";
import { z } from "zod";

export const runtime = "nodejs";

const chatRequestSchema = z.object({
  messages: z
    .array(
      z.object({
        role: z.enum(["system", "user", "assistant"]),
        content: z.string().min(1).max(4000),
      })
    )
    .min(1)
    .max(50),
  symbol: z.string().optional(),
  chain: z.enum(["solana", "bsc", "robinhood"]).optional(),
});

function extractSymbolFromText(text: string): string | null {
  // Check for $SYMBOL (e.g. $PEPEQ, $BONK, $GPU)
  const cashtagMatch = text.match(/\$([A-Za-z0-9]{2,10})\b/);
  if (cashtagMatch && cashtagMatch[1]) {
    return cashtagMatch[1].toUpperCase();
  }

  // Check for common tokens mentioned in caps or keyword patterns
  const tokenMatch = text.match(/\b(PEPEQ|GPU|SOL|BNB|BONK|WIF|TRUMP|PUMP|METEORA)\b/i);
  if (tokenMatch && tokenMatch[1]) {
    return tokenMatch[1].toUpperCase();
  }

  return null;
}

export async function POST(request: Request) {
  const originError = assertTrustedOrigin(request);
  if (originError) {
    return new Response(JSON.stringify({ error: originError }), {
      status: 403,
      headers: { "Content-Type": "application/json" },
    });
  }

  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return new Response(JSON.stringify({ error: "Rate limit exceeded. Please wait a moment." }), {
      status: 429,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    const body = await request.json();
    const parsed = chatRequestSchema.safeParse(body);

    if (!parsed.success) {
      return new Response(
        JSON.stringify({ error: "Invalid request payload", details: parsed.error.flatten() }),
        { status: 400, headers: { "Content-Type": "application/json" } }
      );
    }

    const { messages, chain } = parsed.data;
    const latestUserMessage = [...messages].reverse().find((m) => m.role === "user")?.content || "";

    // 1. Determine target symbol (either explicitly passed or extracted from user message)
    const targetSymbol = parsed.data.symbol?.toUpperCase() || extractSymbolFromText(latestUserMessage);

    let olaxbtSignal: OlaXbtStrategySignal | null = null;
    let onChainContextStr = "";

    // 2. Query OlaXBT signal intelligence if a token is referenced
    if (targetSymbol) {
      try {
        olaxbtSignal = await fetchOlaXbtSignals(targetSymbol);
      } catch (err) {
        console.warn(`[AI] Could not fetch OlaXBT signals for ${targetSymbol}:`, err);
      }

      // Check if token exists in database
      try {
        const supabase = createAdminSupabase();
        const { data: tokenRecord } = await supabase
          .from("tokens")
          .select("id, name, symbol, network, supply, status")
          .ilike("symbol", targetSymbol)
          .order("created_at", { ascending: false })
          .limit(1)
          .maybeSingle();

        if (tokenRecord) {
          onChainContextStr += `\n- On-Chain Token Record: Name="${tokenRecord.name}", Network=${tokenRecord.network}, Supply=${tokenRecord.supply}, Status=${tokenRecord.status}`;
        }
      } catch {
        // Fallback gracefully
      }

    }

    // 3. Assemble dynamic context for the LLM
    let dynamicContext = "";
    if (olaxbtSignal) {
      dynamicContext += `Token: $${olaxbtSignal.symbol}
- OlaXBT Momentum Score: ${olaxbtSignal.momentumScore}/100
- OlaXBT Signal Trend: ${olaxbtSignal.trendDirection.toUpperCase()}
- Strategy Recommendation: ${olaxbtSignal.recommendation}
- 24h Volume Surge: +${olaxbtSignal.volumeSurge24h}%
- Strategy Pattern: ${olaxbtSignal.strategyName}
- Confidence: ${olaxbtSignal.confidence}%${onChainContextStr}`;
    }

    if (chain) {
      dynamicContext += `\n- Active Chain Context: ${chain.toUpperCase()}`;
    }

    // 4. Check if prompt represents trading bot strategy intent
    let strategyPreview = null;
    const isStrategyIntent =
      /strategy|sniper|bot|scalp|take profit|stop loss|auto trade|deploy agent/i.test(latestUserMessage);
    if (isStrategyIntent) {
      try {
        strategyPreview = compilePromptToStrategy(latestUserMessage);
        dynamicContext += `\n\nPROPOSED BOT STRATEGY COMPILED:
- Name: ${strategyPreview.name}
- Chain: ${strategyPreview.rules.chain.toUpperCase()}
- Launchpads: ${strategyPreview.rules.launchpads.join(", ")}
- Take Profit: +${strategyPreview.rules.takeProfitPct}% | Stop Loss: -${strategyPreview.rules.stopLossPct}%
- Allocation per trade: ${strategyPreview.rules.tradeAmount}
- MEV Protection: Enabled (KeeperHub Shield)`;
      } catch {
        // Ignore strategy compiler fallback
      }
    }

    // 5. Call Groq streaming completion
    const groqResponse = await streamGroqChat(messages as ChatMessage[], dynamicContext);

    if (!groqResponse.ok) {
      const errText = await groqResponse.text();
      console.error("[API] Groq stream error:", groqResponse.status, errText);
      return new Response(JSON.stringify({ error: "AI reasoning engine unavailable. Please retry." }), {
        status: 502,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 6. Return standard EventStream / readable stream with metadata headers
    const responseHeaders = new Headers();
    responseHeaders.set("Content-Type", "text/event-stream; charset=utf-8");
    responseHeaders.set("Cache-Control", "no-cache, no-transform");
    responseHeaders.set("Connection", "keep-alive");

    if (olaxbtSignal) {
      responseHeaders.set("X-OlaXBT-Signal", encodeURIComponent(JSON.stringify(olaxbtSignal)));
    }
    if (strategyPreview) {
      responseHeaders.set("X-Strategy-Preview", encodeURIComponent(JSON.stringify(strategyPreview)));
    }

    // Pipe the response body directly to the client
    return new Response(groqResponse.body, {
      status: 200,
      headers: responseHeaders,
    });
  } catch (err: any) {
    console.error("[API] POST /api/ai/chat error:", err);
    return new Response(
      JSON.stringify({ error: err.message || "Failed to process chat conversation." }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}
