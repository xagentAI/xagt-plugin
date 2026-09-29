"use client";

import React, { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useRouter } from "next/navigation";

interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  timestamp: string;
  olaxbtSignal?: {
    symbol: string;
    momentumScore: number;
    trendDirection: "bullish" | "bearish" | "neutral";
    recommendation: string;
    volumeSurge24h: number;
    strategyName: string;
  };
  strategyPreview?: {
    name: string;
    summary: string;
    targetCategory: string;
    rules: {
      chain: string;
      launchpads: string[];
      takeProfitPct: number;
      stopLossPct: number;
      tradeAmount: number;
    };
  };
}

const QUICK_PROMPTS = [
  { label: "Analyze $PEPEQ", prompt: "Analyze $PEPEQ on Solana with OlaXBT momentum score" },
  { label: "Trending Bonding Curves", prompt: "Which bonding curves have the highest momentum and lowest MEV risk?" },
  { label: "Build 25% TP Sniper", prompt: "Build a momentum sniper bot on Solana Meteora with 25% take profit and 10% stop loss" },
  { label: "Explain KeeperHub Shield", prompt: "How does the KeeperHub MEV shield prevent sandwich attacks on bonding curve swaps?" },
];

export function MultipuAiChat() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "intro",
      role: "assistant",
      content:
        "**Multipu AI Online.** Powered by Groq LPU inference and OlaXBT Nexus market signals. Ask me to scan tokens, compute bonding curve velocity, or compile automated sniper strategies.",
      timestamp: "Just now",
    },
  ]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (isOpen) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
      inputRef.current?.focus();
    }
  }, [isOpen, messages]);

  const handleSend = async (customPrompt?: string) => {
    const textToSend = customPrompt || input.trim();
    if (!textToSend || loading) return;

    const userMessageId = "usr_" + Date.now();
    const assistantMessageId = "ast_" + Date.now();

    const newMessages: ChatMessage[] = [
      ...messages,
      {
        id: userMessageId,
        role: "user",
        content: textToSend,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      },
    ];

    setMessages(newMessages);
    setInput("");
    setLoading(true);

    try {
      const res = await fetch("/api/ai/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          messages: newMessages.map((m) => ({ role: m.role, content: m.content })),
        }),
      });

      if (!res.ok) {
        throw new Error(`Failed to send message (${res.status})`);
      }

      // Read metadata headers
      let signalData = undefined;
      const rawSignal = res.headers.get("X-OlaXBT-Signal");
      if (rawSignal) {
        try {
          signalData = JSON.parse(decodeURIComponent(rawSignal));
        } catch {
          // Ignore parse error
        }
      }

      let strategyData = undefined;
      const rawStrategy = res.headers.get("X-Strategy-Preview");
      if (rawStrategy) {
        try {
          strategyData = JSON.parse(decodeURIComponent(rawStrategy));
        } catch {
          // Ignore parse error
        }
      }

      // Prepare assistant placeholder message
      setMessages((prev) => [
        ...prev,
        {
          id: assistantMessageId,
          role: "assistant",
          content: "",
          timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
          olaxbtSignal: signalData,
          strategyPreview: strategyData,
        },
      ]);

      if (!res.body) {
        throw new Error("No response stream body available");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let accumulatedText = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        // Handle OpenAI/Groq SSE format ("data: {...}")
        const lines = chunk.split("\n");
        for (const line of lines) {
          const trimmed = line.trim();
          if (trimmed.startsWith("data: ")) {
            const dataStr = trimmed.replace(/^data:\s*/, "");
            if (dataStr === "[DONE]") continue;
            try {
              const parsed = JSON.parse(dataStr);
              const delta = parsed.choices?.[0]?.delta?.content || "";
              accumulatedText += delta;
            } catch {
              // Raw text chunk fallback
              accumulatedText += dataStr;
            }
          } else if (trimmed && !trimmed.startsWith(":")) {
            // Direct text chunk fallback
            accumulatedText += trimmed;
          }
        }

        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === assistantMessageId ? { ...msg, content: accumulatedText } : msg
          )
        );
      }
    } catch (err: any) {
      console.error("[Multipu AI] Chat error:", err);
      setMessages((prev) => [
        ...prev,
        {
          id: "err_" + Date.now(),
          role: "assistant",
          content: "⚠️ Failed to receive stream from Multipu AI. Please verify network connection.",
          timestamp: "Error",
        },
      ]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {/* Floating Trigger Button */}
      <div className="fixed bottom-6 right-6 z-50">
        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={() => setIsOpen(!isOpen)}
          className="relative group flex items-center gap-3 px-4 py-3 rounded-full bg-[#0a0c14] border border-white/20 shadow-[0_0_25px_rgba(0,0,0,0.8)] text-white hover:border-accent transition-colors duration-200"
        >
          <span className="relative flex h-3 w-3">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-3 w-3 bg-emerald-500" />
          </span>
          <span className="font-mono text-xs tracking-wider uppercase font-semibold">
            Multipu AI
          </span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-accent/20 border border-accent/40 text-accent font-mono font-bold">
            GROQ
          </span>
        </motion.button>
      </div>

      {/* Floating Chat Modal */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 30, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 30, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="fixed bottom-20 right-6 z-50 w-[92vw] sm:w-[460px] h-[580px] max-h-[82vh] flex flex-col bg-[#07090e]/95 backdrop-blur-xl border border-white/15 rounded-2xl shadow-2xl overflow-hidden font-sans"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-white/10 bg-black/40">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-lg bg-accent/10 border border-accent/30 flex items-center justify-center text-accent font-mono font-bold text-sm">
                  AI
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-white font-semibold text-sm">Multipu Copilot</span>
                    <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                      LIVE
                    </span>
                  </div>
                  <div className="text-[11px] text-text-secondary font-mono flex items-center gap-1.5">
                    <span>Groq LPU</span>
                    <span>•</span>
                    <span>OlaXBT Alpha</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-1">
                <button
                  onClick={() =>
                    setMessages([
                      {
                        id: "intro",
                        role: "assistant",
                        content:
                          "**Multipu AI Online.** Powered by Groq LPU inference and OlaXBT Nexus market signals. Ask me to scan tokens, compute bonding curve velocity, or compile automated sniper strategies.",
                        timestamp: "Just now",
                      },
                    ])
                  }
                  title="Clear conversation"
                  className="p-1.5 rounded-lg text-text-secondary hover:text-white hover:bg-white/5 transition-colors text-xs"
                >
                  Clear
                </button>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1.5 rounded-lg text-text-secondary hover:text-white hover:bg-white/5 transition-colors"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Quick Prompts Bar */}
            <div className="flex items-center gap-1.5 px-4 py-2 border-b border-white/5 overflow-x-auto no-scrollbar bg-white/[0.01]">
              {QUICK_PROMPTS.map((qp, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSend(qp.prompt)}
                  disabled={loading}
                  className="shrink-0 text-[11px] font-mono px-2.5 py-1 rounded-md bg-white/[0.04] hover:bg-white/[0.08] text-text-secondary hover:text-white border border-white/10 transition-colors"
                >
                  {qp.label}
                </button>
              ))}
            </div>

            {/* Messages Container */}
            <div className="flex-1 overflow-y-auto p-4 space-y-4 text-xs font-sans">
              {messages.map((msg) => (
                <div
                  key={msg.id}
                  className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}
                >
                  <div
                    className={`max-w-[88%] rounded-xl px-4 py-2.5 leading-relaxed ${
                      msg.role === "user"
                        ? "bg-accent/20 border border-accent/40 text-white"
                        : "bg-white/[0.03] border border-white/10 text-gray-200"
                    }`}
                  >
                    <div className="whitespace-pre-wrap">{msg.content}</div>

                    {/* Rich OlaXBT Signal Card */}
                    {msg.olaxbtSignal && (
                      <div className="mt-3 p-3 rounded-lg bg-black/60 border border-accent/30 font-mono text-[11px] space-y-1.5">
                        <div className="flex items-center justify-between">
                          <span className="text-white font-bold tracking-wide">
                            ${msg.olaxbtSignal.symbol}
                          </span>
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                              msg.olaxbtSignal.recommendation === "Strong Buy"
                                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/40"
                                : "bg-amber-500/20 text-amber-400 border border-amber-500/40"
                            }`}
                          >
                            {msg.olaxbtSignal.recommendation}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-text-secondary">
                          <span>OlaXBT Momentum:</span>
                          <span className="text-accent font-semibold">
                            {msg.olaxbtSignal.momentumScore}/100
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-text-secondary">
                          <span>24h Volume Surge:</span>
                          <span className="text-emerald-400 font-semibold">
                            +{msg.olaxbtSignal.volumeSurge24h}%
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-text-secondary">
                          <span>Strategy Pattern:</span>
                          <span className="text-white">{msg.olaxbtSignal.strategyName}</span>
                        </div>
                      </div>
                    )}

                    {/* Rich Strategy Preview Card */}
                    {msg.strategyPreview && (
                      <div className="mt-3 p-3 rounded-lg bg-emerald-950/20 border border-emerald-500/30 font-mono text-[11px] space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-emerald-400 font-bold">
                            🤖 {msg.strategyPreview.name}
                          </span>
                          <span className="text-[10px] uppercase text-text-secondary">
                            {msg.strategyPreview.rules.chain}
                          </span>
                        </div>
                        <div className="text-text-secondary text-[11px] leading-snug">
                          {msg.strategyPreview.summary}
                        </div>
                        <div className="pt-1 flex gap-2">
                          <button
                            onClick={() => router.push("/dashboard")}
                            className="w-full py-1.5 rounded bg-emerald-500/20 hover:bg-emerald-500/30 border border-emerald-500/50 text-emerald-300 font-semibold text-center transition-colors text-[10px] uppercase tracking-wider"
                          >
                            View in Agent Dashboard →
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] text-text-secondary mt-1 px-1 font-mono">
                    {msg.timestamp}
                  </span>
                </div>
              ))}
              {loading && (
                <div className="flex items-center gap-2 text-text-secondary text-xs px-2 font-mono">
                  <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce" />
                  <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:0.2s]" />
                  <span className="w-1.5 h-1.5 rounded-full bg-accent animate-bounce [animation-delay:0.4s]" />
                  <span className="text-[11px]">Reasoning with Groq LPU...</span>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input Bar */}
            <div className="p-3 border-t border-white/10 bg-black/40">
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  handleSend();
                }}
                className="flex items-center gap-2"
              >
                <input
                  ref={inputRef}
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  placeholder="Ask about tokens, momentum scores, or bots..."
                  disabled={loading}
                  className="flex-1 bg-white/[0.04] border border-white/15 rounded-xl px-3.5 py-2.5 text-xs text-white placeholder:text-text-secondary focus:outline-none focus:border-accent transition-colors font-sans"
                />
                <button
                  type="submit"
                  disabled={!input.trim() || loading}
                  className="px-4 py-2.5 rounded-xl bg-accent text-black font-semibold text-xs disabled:opacity-40 hover:bg-accent/90 transition-all font-mono"
                >
                  Send
                </button>
              </form>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
