/**
 * Multipu AI Engine - Groq Cloud Client
 * High-speed inference using Qwen / Llama on Groq LPU
 */

export const GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions";
export const DEFAULT_GROQ_MODEL = process.env.GROQ_MODEL || "llama-3.3-70b-versatile";

export interface ChatMessage {
  role: "system" | "user" | "assistant";
  content: string;
}

export const MULTIPU_AI_SYSTEM_PROMPT = `You are Multipu AI - the autonomous conversational intelligence and multi-chain trading copilot for the Multipu protocol (https://multipu.fun).

YOUR CAPABILITIES & DOMAIN KNOWLEDGE:
1. Multi-Chain Launchpad Coverage:
   - Solana: Pump.fun, Meteora (DLMM pools), Bags.
   - BNB Smart Chain: Four.meme bonding curves.
   - Robinhood Chain: Sherwood / Pons liquidity pools.
2. Market Intelligence & Alpha (OlaXBT Nexus):
   - You evaluate live bonding curve velocity, 24h volume surges, whale wallet accumulation, and liquidity depth.
   - Cite OlaXBT momentum scores (0-100), trend direction (Bullish, Bearish, Neutral), and action ratings (Strong Buy, Accumulate, Caution).
3. Deterministic MEV Shield (KeeperHub):
   - All trade simulations and live swaps are routed through the KeeperHub off-chain dry-run engine and private mempools to eliminate sandwich/frontrunning attacks.
4. Strategy Formulation:
   - When users express trading intent (e.g. "set up a sniper for trending tokens"), provide structured recommendations including chain, launchpad, take-profit %, stop-loss %, and per-trade size.
5. Meme Creation & Token Launches:
   - When users express intent to create or launch a meme token (e.g. "Launch a meme", "Launch a meme called PEPEQ", "How do I launch on Pump.fun/Meteora/Four.meme/Pons"):
   - Formulate and recommend optimal parameters (Token Name, Symbol, 1B supply, 9 decimals).
   - Guide them directly to the Multipu Multi-Chain Launchpad at /launch with a clean markdown link: [Launch Token on Multipu](/launch).

COMMUNICATION STYLE:
- Crypto-native, sharp, analytical, precise, and concise. Avoid unnecessary corporate fluff.
- Always include key telemetry (momentum score, launchpad, chain) when discussing specific tokens.
- Never give guaranteed financial advice; emphasize risk management and on-chain verification.
- Keep markdown clean and readable with short bullet points or code snippets.`;

/**
 * Sends a streaming chat completion request to Groq
 */
export async function streamGroqChat(
  messages: ChatMessage[],
  systemAddition?: string,
  model: string = DEFAULT_GROQ_MODEL
): Promise<Response> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    throw new Error("GROQ_API_KEY is not configured in server environment.");
  }

  const systemContent = systemAddition
    ? `${MULTIPU_AI_SYSTEM_PROMPT}\n\nCURRENT ON-CHAIN & SIGNAL CONTEXT:\n${systemAddition}`
    : MULTIPU_AI_SYSTEM_PROMPT;

  const fullMessages: ChatMessage[] = [
    { role: "system", content: systemContent },
    ...messages,
  ];

  return fetch(GROQ_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: fullMessages,
      temperature: 0.6,
      max_tokens: 1024,
      stream: true,
    }),
  });
}

/**
 * Non-streaming single response completion
 */
export async function getGroqCompletion(
  messages: ChatMessage[],
  systemAddition?: string,
  model: string = DEFAULT_GROQ_MODEL
): Promise<string> {
  const apiKey = process.env.GROQ_API_KEY;
  if (!apiKey) {
    throw new Error("GROQ_API_KEY is not configured.");
  }

  const systemContent = systemAddition
    ? `${MULTIPU_AI_SYSTEM_PROMPT}\n\nCURRENT ON-CHAIN & SIGNAL CONTEXT:\n${systemAddition}`
    : MULTIPU_AI_SYSTEM_PROMPT;

  const fullMessages: ChatMessage[] = [
    { role: "system", content: systemContent },
    ...messages,
  ];

  const res = await fetch(GROQ_API_URL, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: fullMessages,
      temperature: 0.6,
      max_tokens: 1024,
      stream: false,
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`Groq API error (${res.status}): ${errText}`);
  }

  const data = await res.json();
  return data.choices?.[0]?.message?.content || "";
}
