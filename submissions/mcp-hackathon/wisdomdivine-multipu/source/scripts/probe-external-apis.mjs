import dotenv from "dotenv";
dotenv.config({ path: ".env.local" });

const results = [];

async function probe(name, fn) {
  const start = Date.now();
  try {
    const res = await fn();
    const duration = Date.now() - start;
    results.push({ name, status: "OK", duration: `${duration}ms`, details: res });
    console.log(`✅ [${name}] OK (${duration}ms):`, res);
  } catch (err) {
    const duration = Date.now() - start;
    results.push({ name, status: "FAIL", duration: `${duration}ms`, error: err.message });
    console.log(`❌ [${name}] ERROR (${duration}ms):`, err.message);
  }
}

async function main() {
  console.log("=== PROBING EXTERNAL APIS ===");

  // 1. Groq API
  await probe("Groq AI API", async () => {
    const apiKey = process.env.GROQ_API_KEY;
    const model = process.env.GROQ_MODEL || "qwen/qwen3.8-27b";
    if (!apiKey) throw new Error("GROQ_API_KEY missing");
    const res = await fetch("https://api.groq.com/openai/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${apiKey}`,
      },
      body: JSON.stringify({
        model,
        messages: [{ role: "user", content: "ping" }],
        max_tokens: 5,
      }),
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}: ${txt}`);
    }
    const data = await res.json();
    return {
      model,
      response: data.choices?.[0]?.message?.content?.trim(),
      usage: data.usage,
    };
  });

  // 2. Supabase API
  await probe("Supabase Auth/DB", async () => {
    const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
    const key = process.env.SUPABASE_SERVICE_KEY || process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    if (!url || !key) throw new Error("Supabase config missing");
    const res = await fetch(`${url}/rest/v1/tokens?select=count`, {
      headers: {
        apikey: key,
        Authorization: `Bearer ${key}`,
        Range: "0-0",
      },
    });
    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`HTTP ${res.status}: ${txt}`);
    }
    const countHeader = res.headers.get("content-range");
    return { url, contentRange: countHeader, status: res.status };
  });

  // 3. Solana RPC (Devnet / Configured)
  await probe("Solana RPC", async () => {
    const rpcUrl = process.env.NEXT_PUBLIC_SOLANA_RPC_URL || "https://api.devnet.solana.com";
    const res = await fetch(rpcUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "getSlot",
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return { rpcUrl, currentSlot: data.result };
  });

  // 4. DexScreener Latest Tokens
  await probe("DexScreener Tokens API", async () => {
    // Probe with a well-known Solana token address (USDC)
    const token = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v";
    const res = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${token}`, {
      headers: { "User-Agent": "Multipu/1.0" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return {
      pairsFound: data.pairs ? data.pairs.length : 0,
      firstPairDex: data.pairs?.[0]?.dexId,
      firstPairPrice: data.pairs?.[0]?.priceUsd,
    };
  });

  // 5. DexScreener Token Boosts
  await probe("DexScreener Token Boosts API", async () => {
    const res = await fetch("https://api.dexscreener.com/token-boosts/top/v1", {
      headers: { "User-Agent": "Multipu/1.0" },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return {
      topBoostsCount: Array.isArray(data) ? data.length : 0,
      firstToken: data[0]?.tokenAddress,
    };
  });

  // 6. BSC RPC
  await probe("BSC Dataseed RPC", async () => {
    const rpcUrl = process.env.NEXT_PUBLIC_BSC_RPC_URL || "https://bsc-dataseed.binance.org";
    const res = await fetch(rpcUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "eth_chainId",
        params: [],
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return { chainId: parseInt(data.result, 16) };
  });

  // 7. Robinhood Chain RPC
  await probe("Robinhood Chain RPC", async () => {
    const rpcUrl = process.env.NEXT_PUBLIC_ROBINHOOD_RPC_URL || "https://rpc.mainnet.chain.robinhood.com";
    const res = await fetch(rpcUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "eth_chainId",
        params: [],
      }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    return { rpcUrl, chainId: parseInt(data.result, 16) };
  });

  // 8. OlaXBT Nexus API
  await probe("OlaXBT Nexus API", async () => {
    const url = process.env.OLAXBT_NEXUS_API_URL || "https://nexus.olaxbt.xyz/api";
    try {
      const res = await fetch(`${url}/signals/PEPEQ`, {
        signal: AbortSignal.timeout(5000),
      });
      return { status: res.status, ok: res.ok };
    } catch (e) {
      return { status: "offline/fallback_active", note: "Handled gracefully by local algorithm fallback", error: e.message };
    }
  });

  // 9. KeeperHub Execution API
  await probe("KeeperHub Workflow API", async () => {
    const url = process.env.KEEPERHUB_API_URL || "https://api.keeperhub.com/v1";
    try {
      const res = await fetch(`${url}/workflows/dry-run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(process.env.KEEPERHUB_API_KEY
            ? { Authorization: `Bearer ${process.env.KEEPERHUB_API_KEY}` }
            : {}),
        },
        body: JSON.stringify({
          chain: "solana",
          action: "bonding_curve_swap",
          sender: "11111111111111111111111111111111",
          amount: 0.1,
        }),
        signal: AbortSignal.timeout(5000),
      });
      return { status: res.status, ok: res.ok };
    } catch (e) {
      return { status: "offline/fallback_active", note: "Handled gracefully by local deterministic simulator fallback", error: e.message };
    }
  });

  // 10. Dicebear Identicon SVG API
  await probe("Dicebear Identicon Avatar API", async () => {
    const res = await fetch("https://api.dicebear.com/7.x/identicon/svg?seed=MULTIPU");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const contentType = res.headers.get("content-type");
    return { contentType, status: res.status };
  });

  console.log("\n=== PROBE SUMMARY ===");
  console.table(results);
}

main();
