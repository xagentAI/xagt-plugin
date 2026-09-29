#!/usr/bin/env node
/**
 * EXHAUSTIVE E2E API TEST SUITE — Multipu
 *
 * Hits every API route over HTTP against the running dev server.
 * Skips tests that require real money (mainnet txns, real wallet signatures).
 *
 * Usage: node scripts/test-api-e2e.mjs
 */

const BASE = process.env.BASE_URL || "http://localhost:3847";
const ORIGIN = BASE;

let passed = 0;
let failed = 0;
let skipped = 0;
const results = [];

function log(icon, msg) {
  const line = `${icon} ${msg}`;
  console.log(line);
  results.push(line);
}

function assert(condition, label) {
  if (condition) { passed++; log("✅", `PASS: ${label}`); }
  else           { failed++; log("❌", `FAIL: ${label}`); }
}

function skip(label, reason) {
  skipped++;
  log("⏭️ ", `SKIP: ${label} — ${reason}`);
}

// Tracks all cookies across set-cookie headers
let cookieJar = {};

function mergeCookies(setCookieHeaders) {
  for (const sc of setCookieHeaders) {
    const [pair] = sc.split(";");
    const [name, ...valueParts] = pair.split("=");
    cookieJar[name.trim()] = valueParts.join("=");
  }
}

function cookieString() {
  return Object.entries(cookieJar).map(([k, v]) => `${k}=${v}`).join("; ");
}

async function req(method, path, body, extra = {}) {
  const url = `${BASE}${path}`;
  const headers = {
    "Content-Type": "application/json",
    "Origin": ORIGIN,
    "Host": new URL(BASE).host,
    ...(extra.headers || {}),
  };
  const opts = { method, headers, redirect: "manual" };
  if (body) opts.body = JSON.stringify(body);
  if (extra.cookie) headers["Cookie"] = extra.cookie;
  const res = await fetch(url, opts);
  // Merge any set-cookie headers into our jar
  const sc = res.headers.getSetCookie?.() || [];
  if (sc.length) mergeCookies(sc);
  let json = null;
  const text = await res.text();
  try { json = JSON.parse(text); } catch {}
  return { status: res.status, json, text, headers: res.headers };
}

// ─── Helpers ────────────────────────────────────────────

async function loginDemo(wallet = "demo_test_wallet_e2e") {
  const r = await req("POST", "/api/auth/demo", { walletAddress: wallet });
  return r;
}

function authReq(method, path, body) {
  return req(method, path, body, { cookie: cookieString() });
}

// ═══════════════════════════════════════════════════════
//   TESTS
// ═══════════════════════════════════════════════════════

async function run() {
  console.log("═".repeat(60));
  console.log("  MULTIPU EXHAUSTIVE API E2E TEST SUITE");
  console.log("  Target: " + BASE);
  console.log("═".repeat(60) + "\n");

  // ─── 1. Health ────────────────────────────────────────
  console.log("─── 1. GET /api/health ───");
  {
    const r = await req("GET", "/api/health");
    assert(r.status === 200, "/api/health returns 200");
    assert(r.json?.status === "ok", "/api/health status field is 'ok'");
    assert(typeof r.json?.environment?.appPhase === "string", "/api/health includes appPhase");
    assert(typeof r.json?.environment?.network === "string", "/api/health includes network");
  }

  // ─── 2. Auth: Session (unauthenticated) ──────────────
  console.log("\n─── 2. GET /api/auth/session (no auth) ───");
  {
    const r = await req("GET", "/api/auth/session");
    assert(r.status === 200, "/api/auth/session returns 200 when unauthenticated");
    assert(r.json?.isLoggedIn === false, "Session reports isLoggedIn=false");
  }

  // ─── 3. Auth: Challenge (Solana) ─────────────────────
  console.log("\n─── 3. GET /api/auth/challenge ───");
  {
    const r = await req("GET", "/api/auth/challenge");
    assert(r.status === 200, "/api/auth/challenge returns 200");
    assert(typeof r.json?.nonce === "string" && r.json.nonce.length > 10, "Challenge returns a nonce string");
  }

  // ─── 4. Auth: Challenge-EVM ──────────────────────────
  console.log("\n─── 4. GET /api/auth/challenge-evm ───");
  {
    const r = await req("GET", "/api/auth/challenge-evm");
    assert(r.status === 200, "/api/auth/challenge-evm returns 200");
    assert(typeof r.json?.nonce === "string", "EVM challenge returns nonce");
  }

  // ─── 5. Auth: Verify (invalid sig ─ should fail) ─────
  console.log("\n─── 5. POST /api/auth/verify (invalid sig) ───");
  {
    const r = await req("POST", "/api/auth/verify", {
      walletAddress: "FakeWalletAddr1111111111111111111111111111",
      signature: "invalidsig",
      nonce: "invalidnonce",
    });
    assert(r.status >= 400, "/api/auth/verify rejects invalid signature (" + r.status + ")");
  }

  // ─── 6. Auth: Verify-EVM (invalid sig ─ should fail) ─
  console.log("\n─── 6. POST /api/auth/verify-evm (invalid sig) ───");
  {
    const r = await req("POST", "/api/auth/verify-evm", {
      walletAddress: "0x0000000000000000000000000000000000000000",
      signature: "0xinvalid",
      nonce: "invalidnonce",
    });
    assert(r.status >= 400, "/api/auth/verify-evm rejects invalid EVM signature (" + r.status + ")");
  }

  // ─── 7. Auth: Demo Login ─────────────────────────────
  console.log("\n─── 7. POST /api/auth/demo ───");
  {
    const r = await loginDemo();
    assert(r.status === 200, "/api/auth/demo returns 200");
    assert(r.json?.ok === true, "Demo login ok=true");
    assert(cookieString().length > 0, "Session cookie was set");
  }

  // ─── 8. Auth: Session (authenticated) ────────────────
  console.log("\n─── 8. GET /api/auth/session (authenticated) ───");
  {
    const r = await authReq("GET", "/api/auth/session");
    assert(r.status === 200, "/api/auth/session returns 200");
    assert(r.json?.isLoggedIn === true, "Session reports isLoggedIn=true");
    assert(r.json?.walletAddress === "demo_test_wallet_e2e", "Session walletAddress correct");
  }

  // ─── 9. OlaXBT Signals ──────────────────────────────
  console.log("\n─── 9. GET /api/olaxbt/signals ───");
  {
    const r = await req("GET", "/api/olaxbt/signals?symbol=PEPEQ");
    assert(r.status === 200, "/api/olaxbt/signals returns 200");
    assert(typeof r.json?.signal?.symbol === "string", "Signal has symbol field");
    assert(typeof r.json?.signal?.momentumScore === "number", "Signal has momentumScore");
    assert(typeof r.json?.signal?.trendDirection === "string", "Signal has trendDirection");
  }

  // ─── 10. Dashboard ──────────────────────────────────
  console.log("\n─── 10. GET /api/dashboard ───");
  {
    const r = await authReq("GET", "/api/dashboard");
    assert(r.status === 200, "/api/dashboard returns 200");
    assert(r.json !== null, "Dashboard returns data structure");
  }

  // ─── 11. Dashboard Exposure ─────────────────────────
  console.log("\n─── 11. GET /api/dashboard/exposure ───");
  {
    const r = await authReq("GET", "/api/dashboard/exposure");
    assert(r.status === 200, "/api/dashboard/exposure returns 200");
  }

  // ─── 12. Notifications ─────────────────────────────
  console.log("\n─── 12. GET /api/notifications ───");
  {
    const r = await authReq("GET", "/api/notifications");
    assert(r.status === 200, "/api/notifications returns 200");
    assert(Array.isArray(r.json?.notifications), "Notifications returns an array");
  }

  // ─── 13. Wallet Balances ───────────────────────────
  console.log("\n─── 13. GET /api/wallet/balances ───");
  {
    const r = await authReq("GET", "/api/wallet/balances");
    assert(r.status === 200, "/api/wallet/balances returns 200");
    assert(r.json !== null, "Wallet balances returns data");
  }

  // ─── 14. Tokens: GET (list) ────────────────────────
  console.log("\n─── 14. GET /api/tokens ───");
  {
    const r = await authReq("GET", "/api/tokens");
    assert(r.status === 200, "/api/tokens GET returns 200");
    assert(Array.isArray(r.json?.tokens), "Tokens returns an array");
  }

  // ─── 15. Tokens: POST (create) ────────────────────
  console.log("\n─── 15. POST /api/tokens ───");
  let createdTokenId = null;
  {
    const r = await authReq("POST", "/api/tokens", {
      name: "E2E Test Token",
      symbol: "E2ETEST",
      supply: "1000000000",
      decimals: 9,
      description: "Automated e2e test token",
    });
    assert(r.status === 201 || r.status === 200, "/api/tokens POST returns 201/200 (" + r.status + ")");
    if (r.json?.token?.id) {
      createdTokenId = r.json.token.id;
      assert(true, "Token ID created: " + createdTokenId);
    } else {
      assert(false, "Token creation did not return an ID");
    }
  }

  // ─── 16. Tokens: POST validation error ────────────
  console.log("\n─── 16. POST /api/tokens (validation error) ───");
  {
    const r = await authReq("POST", "/api/tokens", {
      name: "",
      symbol: "",
      supply: "-1",
    });
    assert(r.status === 400, "/api/tokens POST rejects invalid input (" + r.status + ")");
  }

  // ─── 17. Launches: GET (list) ─────────────────────
  console.log("\n─── 17. GET /api/launches ───");
  {
    const r = await authReq("GET", "/api/launches");
    assert(r.status === 200, "/api/launches GET returns 200");
    assert(Array.isArray(r.json?.launches), "Launches returns an array");
  }

  // ─── 18. Launches: POST (create) ─────────────────
  console.log("\n─── 18. POST /api/launches ───");
  {
    // Tokens must be minted before launching — this is an expected business rule
    if (createdTokenId) {
      const r = await authReq("POST", "/api/launches", {
        tokenId: createdTokenId,
        launchpad: "pumpfun",
        initialLiquidity: 1.0,
      });
      // 400 = "Token must be minted" is valid business logic, not a crash
      assert(r.status === 400 || r.status === 201 || r.status === 200,
        "/api/launches POST returns expected status (" + r.status + ": " + (r.json?.error || "ok") + ")");
    } else {
      skip("/api/launches POST", "No token was created");
    }
  }

  // ─── 19. Launches: POST validation error ──────────
  console.log("\n─── 19. POST /api/launches (bad input) ───");
  {
    const r = await authReq("POST", "/api/launches", {
      tokenId: "not-a-uuid",
      launchpad: "unknown_pad",
    });
    assert(r.status === 400, "/api/launches POST rejects invalid input (" + r.status + ")");
  }

  // ─── 20. Launches: Explore ────────────────────────
  console.log("\n─── 20. GET /api/launches/explore ───");
  {
    const r = await req("GET", "/api/launches/explore");
    assert(r.status === 200, "/api/launches/explore returns 200");
    assert(r.json !== null, "Explore returns data structure");
  }

  // ─── 21. Launches: Explore with query ─────────────
  console.log("\n─── 21. GET /api/launches/explore?q=test ───");
  {
    const r = await req("GET", "/api/launches/explore?q=test");
    assert(r.status === 200, "/api/launches/explore?q=test returns 200");
  }

  // ─── 22. Launches: [id] GET 404 ───────────────────
  console.log("\n─── 22. GET /api/launches/[id] (404) ───");
  {
    const r = await authReq("GET", "/api/launches/00000000-0000-0000-0000-000000000000");
    assert(r.status === 404, "/api/launches/fake-id returns 404 (" + r.status + ")");
  }

  // ─── 23. Earnings ────────────────────────────────
  console.log("\n─── 23. GET /api/earnings ───");
  {
    const r = await authReq("GET", "/api/earnings");
    assert(r.status === 200, "/api/earnings returns 200");
  }

  // ─── 24. Agents: GET (list) ─────────────────────
  console.log("\n─── 24. GET /api/agents ───");
  {
    const r = await authReq("GET", "/api/agents");
    assert(r.status === 200, "/api/agents GET returns 200");
    assert(r.json?.success === true, "Agents success=true");
    assert(Array.isArray(r.json?.agents), "Agents returns array");
  }

  // ─── 25. Agents: POST (create) ──────────────────
  console.log("\n─── 25. POST /api/agents ───");
  {
    const r = await authReq("POST", "/api/agents", {
      name: "E2E Sniper Bot",
      description: "Automated test agent",
      prompt: "Scalp Pump.fun memes with >$5k volume",
      mode: "paper",
      chain: "solana",
      launchpads: ["pumpfun", "meteora"],
      strategyConfig: { takeProfitPct: 25, stopLossPct: 10 },
      budgetAllocated: 0.5,
    });
    assert(r.status === 201 || r.status === 200, "/api/agents POST returns 201/200 (" + r.status + ")");
  }

  // ─── 26. Agents: Parse Strategy ─────────────────
  console.log("\n─── 26. POST /api/agents/parse-strategy ───");
  {
    const r = await authReq("POST", "/api/agents/parse-strategy", {
      prompt: "Scalp fresh Pump.fun memes on Solana with >$5k volume. Take profit at +35%, stop loss at -12%. Max 0.2 SOL per trade.",
    });
    assert(r.status === 200, "/api/agents/parse-strategy returns 200");
    assert(r.json?.strategy?.rules?.chain === "solana", "Parsed strategy chain is solana");
    assert(r.json?.strategy?.rules?.takeProfitPct === 35, "TP parsed as 35%");
    assert(r.json?.strategy?.rules?.stopLossPct === 12, "SL parsed as 12%");
  }

  // ─── 27. Agents: Simulate (with full schema) ──────
  console.log("\n─── 27. POST /api/agents/simulate ───");
  {
    const r = await authReq("POST", "/api/agents/simulate", {
      rules: {
        chain: "solana",
        launchpads: ["pumpfun", "meteora"],
        minVolume24hUsd: 5000,
        minLiquiditySol: 10,
        minOlaXbtScore: 72,
        maxTokenAgeHours: 24,
        tradeAmount: 0.2,
        takeProfitPct: 25,
        stopLossPct: 10,
        maxSlippagePct: 5,
        maxDailyTrades: 10,
        mevProtection: true,
        honeypotCheck: true,
      },
    });
    assert(r.status === 200, "/api/agents/simulate returns 200 (" + r.status + ")");
    if (r.json?.simulation) {
      assert(typeof r.json.simulation.simulatedTrades === "number", "Simulation has simulatedTrades");
      assert(typeof r.json.simulation.winRatePct === "number", "Simulation has winRatePct");
      assert(typeof r.json.simulation.expectedPnlPct === "number", "Simulation has expectedPnlPct");
      assert(r.json.simulation.executionEngine?.includes("KeeperHub"), "Simulation engine is KeeperHub");
      assert(Array.isArray(r.json.simulation.sampleTokens), "Simulation returns sampleTokens array");
    } else {
      assert(false, "No simulation object in response: " + JSON.stringify(r.json));
    }
  }

  // ─── 28. Agents: Simulate (bad input) ────────────
  console.log("\n─── 28. POST /api/agents/simulate (bad input) ───");
  {
    const r = await authReq("POST", "/api/agents/simulate", {
      rules: { chain: "invalid_chain" },
    });
    assert(r.status === 400, "/api/agents/simulate rejects bad input (" + r.status + ")");
  }

  // ─── 29. Agents: Execute (paper trade) ─────────
  console.log("\n─── 29. POST /api/agents/execute (paper) ───");
  {
    const r = await authReq("POST", "/api/agents/execute", {
      agentId: "e2e_test_agent",
      tokenSymbol: "PEPEQ",
      action: "buy",
      launchpad: "pumpfun",
      chain: "solana",
      amount: 0.1,
      mode: "paper",
    });
    assert(r.status === 200, "/api/agents/execute paper returns 200");
    assert(r.json?.success === true, "Execute success=true");
    assert(r.json?.trade?.txHash?.startsWith("sim_"), "Paper trade has sim_ hash");
    assert(r.json?.trade?.mode === "paper", "Mode is paper");
  }

  // ─── 30. Agents: Execute (strategy deploy) ─────
  console.log("\n─── 30. POST /api/agents/execute (strategy deploy) ───");
  {
    const r = await authReq("POST", "/api/agents/execute", {
      rules: {
        chain: "solana",
        launchpads: ["pumpfun"],
        takeProfitPct: 30,
        stopLossPct: 15,
        tradeAmount: 0.15,
      },
      mode: "paper",
    });
    assert(r.status === 200, "/api/agents/execute strategy deploy returns 200");
    assert(r.json?.success === true, "Strategy deploy success=true");
    assert(typeof r.json?.session?.id === "string", "Strategy deploy returns session.id");
  }

  // ─── 31. KeeperHub Execute (dry-run) ──────────
  console.log("\n─── 31. POST /api/keeperhub/execute (dryRun) ───");
  {
    const r = await authReq("POST", "/api/keeperhub/execute", {
      chain: "solana",
      action: "bonding_curve_swap",
      amount: 0.1,
      dryRun: true,
      data: { tokenSymbol: "PEPEQ" },
    });
    assert(r.status === 200, "/api/keeperhub/execute dryRun returns 200");
    assert(r.json?.success === true, "KeeperHub dry-run success=true");
    assert(typeof r.json?.simulation?.mevRiskScore === "string", "Dry-run returns mevRiskScore");
  }

  // ─── 32. KeeperHub Execute (live execution) ───
  console.log("\n─── 32. POST /api/keeperhub/execute (live exec) ───");
  {
    const r = await authReq("POST", "/api/keeperhub/execute", {
      chain: "solana",
      action: "bonding_curve_swap",
      amount: 0.05,
      dryRun: false,
      data: { tokenSymbol: "PEPEQ" },
    });
    assert(r.status === 200, "/api/keeperhub/execute live returns 200");
    assert(r.json?.success === true, "KeeperHub live exec success=true");
    assert(typeof r.json?.result?.txHash === "string", "KeeperHub returns txHash");
  }

  // ─── 33. KeeperHub Execute (bad input) ─────────
  console.log("\n─── 33. POST /api/keeperhub/execute (bad input) ───");
  {
    const r = await authReq("POST", "/api/keeperhub/execute", {
      chain: "invalid_chain",
      action: "nope",
      amount: -1,
    });
    assert(r.status === 400, "/api/keeperhub/execute rejects bad input (" + r.status + ")");
  }

  // ─── 34. AI Chat (streaming) ──────────────────
  console.log("\n─── 34. POST /api/ai/chat ───");
  {
    const r = await authReq("POST", "/api/ai/chat", {
      messages: [
        { role: "user", content: "What is $PEPEQ momentum score right now?" },
      ],
      symbol: "PEPEQ",
      chain: "solana",
    });
    assert(r.status === 200, "/api/ai/chat returns 200 (stream)");
    assert(r.text.length > 0, "AI chat returns stream data (length: " + r.text.length + ")");
    const signalHeader = r.headers.get("x-olaxbt-signal");
    assert(typeof signalHeader === "string" && signalHeader.length > 0, "AI chat returns X-OlaXBT-Signal header");
  }

  // ─── 35. AI Chat (strategy intent) ───────────
  console.log("\n─── 35. POST /api/ai/chat (strategy intent) ───");
  {
    const r = await authReq("POST", "/api/ai/chat", {
      messages: [
        { role: "user", content: "Build a sniper bot on Pump.fun with 25% take profit and 10% stop loss, 0.2 SOL per trade." },
      ],
    });
    assert(r.status === 200, "/api/ai/chat strategy intent returns 200");
    const strategyHeader = r.headers.get("x-strategy-preview");
    assert(typeof strategyHeader === "string" && strategyHeader.length > 0, "AI chat returns X-Strategy-Preview header for strategy intent");
  }

  // ─── 36. AI Chat (validation error) ──────────
  console.log("\n─── 36. POST /api/ai/chat (bad input) ───");
  {
    const r = await authReq("POST", "/api/ai/chat", {
      messages: [],
    });
    assert(r.status === 400, "/api/ai/chat rejects empty messages (" + r.status + ")");
  }

  // ─── 37. Trade Swap (non-existent launch) ────
  console.log("\n─── 37. POST /api/trade/swap ───");
  {
    const r = await authReq("POST", "/api/trade/swap", {
      launchId: "00000000-0000-0000-0000-000000000000",
      type: "buy",
      amountPay: 0.1,
      amountReceive: 1000,
    });
    assert(r.status === 404, "/api/trade/swap returns 404 for non-existent launch (" + r.status + ")");
  }

  // ─── 38. Trade Swap (bad input) ──────────────
  console.log("\n─── 38. POST /api/trade/swap (bad input) ───");
  {
    const r = await authReq("POST", "/api/trade/swap", {
      launchId: "not-a-uuid",
      type: "invalid",
      amountPay: -1,
    });
    assert(r.status === 400, "/api/trade/swap rejects bad input (" + r.status + ")");
  }

  // ─── 39. Developer: API Keys GET ─────────────
  console.log("\n─── 39. GET /api/developer/api-keys ───");
  {
    const r = await authReq("GET", "/api/developer/api-keys");
    assert(r.status === 200, "/api/developer/api-keys GET returns 200");
  }

  // ─── 40. Developer: API Keys POST ────────────
  console.log("\n─── 40. POST /api/developer/api-keys ───");
  let createdApiKeyId = null;
  {
    const r = await authReq("POST", "/api/developer/api-keys", {
      name: "E2E Test Key",
    });
    assert(r.status === 200 || r.status === 201, "/api/developer/api-keys POST returns 200/201 (" + r.status + ")");
    if (r.json?.key?.id) {
      createdApiKeyId = r.json.key.id;
      assert(true, "API key generated with ID: " + createdApiKeyId);
    }
  }

  // ─── 41. Developer: API Keys DELETE ──────────
  console.log("\n─── 41. DELETE /api/developer/api-keys ───");
  if (createdApiKeyId) {
    const r = await authReq("DELETE", "/api/developer/api-keys?id=" + createdApiKeyId);
    assert(r.status === 200, "/api/developer/api-keys DELETE returns 200 (" + r.status + ")");
  } else {
    skip("DELETE /api/developer/api-keys", "No API key was created");
  }

  // ─── 42. Developer: Wallet GET ───────────────
  console.log("\n─── 42. GET /api/developer/wallet ───");
  {
    const r = await authReq("GET", "/api/developer/wallet");
    assert(r.status === 200, "/api/developer/wallet GET returns 200");
  }

  // ─── 43. Upload (no file) ────────────────────
  console.log("\n─── 43. POST /api/upload (no file) ───");
  {
    const form = new FormData();
    const r = await fetch(`${BASE}/api/upload`, {
      method: "POST",
      headers: {
        "Cookie": cookieString(),
        "Origin": ORIGIN,
        "Host": new URL(BASE).host,
      },
      body: form,
    });
    assert(r.status === 400, "/api/upload rejects empty form (" + r.status + ")");
  }

  // ─── 44. Upload (wrong file type) ────────────
  console.log("\n─── 44. POST /api/upload (wrong type) ───");
  {
    const form = new FormData();
    form.append("file", new Blob(["not an image"], { type: "text/plain" }), "test.txt");
    const r = await fetch(`${BASE}/api/upload`, {
      method: "POST",
      headers: {
        "Cookie": cookieString(),
        "Origin": ORIGIN,
        "Host": new URL(BASE).host,
      },
      body: form,
    });
    assert(r.status === 400, "/api/upload rejects non-image file (" + r.status + ")");
  }

  // ─── 45. Upload (valid image) ────────────────
  console.log("\n─── 45. POST /api/upload (valid PNG) ───");
  {
    // Minimal valid 1x1 PNG
    const pngBytes = new Uint8Array([
      0x89,0x50,0x4E,0x47,0x0D,0x0A,0x1A,0x0A,0x00,0x00,0x00,0x0D,0x49,0x48,0x44,0x52,
      0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x01,0x08,0x02,0x00,0x00,0x00,0x90,0x77,0x53,
      0xDE,0x00,0x00,0x00,0x0C,0x49,0x44,0x41,0x54,0x08,0xD7,0x63,0xF8,0xCF,0xC0,0x00,
      0x00,0x00,0x02,0x00,0x01,0xE2,0x21,0xBC,0x33,0x00,0x00,0x00,0x00,0x49,0x45,0x4E,
      0x44,0xAE,0x42,0x60,0x82,
    ]);
    const form = new FormData();
    form.append("file", new Blob([pngBytes], { type: "image/png" }), "test.png");
    const r = await fetch(`${BASE}/api/upload`, {
      method: "POST",
      headers: {
        "Cookie": cookieString(),
        "Origin": ORIGIN,
        "Host": new URL(BASE).host,
      },
      body: form,
    });
    const json = await r.json().catch(() => null);
    // 200 or 201 both valid, 500 only if Supabase storage bucket doesn't exist
    assert([200, 201].includes(r.status), "/api/upload processes valid PNG (" + r.status + ")");
    if (json?.url) {
      assert(json.url.startsWith("http"), "Upload returns public URL");
    }
  }

  // ─── 46. Unauthenticated guard tests ─────────
  console.log("\n─── 46. Unauthenticated guard tests ───");
  const guardedRoutes = [
    ["GET", "/api/dashboard"],
    ["GET", "/api/notifications"],
    ["GET", "/api/earnings"],
    ["POST", "/api/tokens"],
    ["GET", "/api/launches"],
    ["POST", "/api/launches"],
    ["POST", "/api/keeperhub/execute"],
    ["POST", "/api/trade/swap"],
    ["GET", "/api/developer/api-keys"],
  ];
  for (const [method, path] of guardedRoutes) {
    // Use a fresh request with NO cookies
    const url = `${BASE}${path}`;
    const headers = {
      "Content-Type": "application/json",
      "Origin": ORIGIN,
      "Host": new URL(BASE).host,
    };
    const opts = { method, headers, redirect: "manual" };
    if (method === "POST") opts.body = JSON.stringify({});
    const res = await fetch(url, opts);
    await res.text();
    assert(res.status === 401, `${method} ${path} returns 401 without auth (${res.status})`);
  }

  // ─── 47. Auth: Logout ────────────────────────
  console.log("\n─── 47. DELETE /api/auth/session (logout) ───");
  {
    const r = await authReq("DELETE", "/api/auth/session");
    assert(r.status === 200, "/api/auth/session DELETE returns 200");
  }

  // ─── 48. Verify logout worked ────────────────
  console.log("\n─── 48. GET /api/auth/session (post-logout) ───");
  {
    // Use updated cookies from DELETE response (which clears the session)
    const r = await authReq("GET", "/api/auth/session");
    assert(r.status === 200, "Session endpoint still 200 post-logout");
    assert(r.json?.isLoggedIn === false, "Session isLoggedIn=false after logout");
  }

  // ═══════════════════════════════════════════════
  // SKIPPED TESTS (require real money / wallets)
  // ═══════════════════════════════════════════════
  console.log("\n─── Skipped Tests (real $$$) ───");
  skip("POST /api/auth/verify (valid Solana sig)", "Requires real Solana wallet keypair to sign");
  skip("POST /api/auth/verify-evm (valid EVM sig)", "Requires real EVM wallet private key to sign");
  skip("POST /api/launches (with minted token)", "Requires real on-chain Solana mint transaction");
  skip("PATCH /api/launches (confirm real launch)", "Requires real on-chain transaction signature");
  skip("POST /api/agents/execute (live mode)", "Requires real funds for KeeperHub on-chain execution");
  skip("POST /api/trade/swap (with live launch)", "Requires live launch with real on-chain pool");
  skip("POST /api/developer/wallet (generate)", "Generates real Solana/EVM keypair, side-effect heavy");

  // ═══════════════════════════════════════════════
  //   SUMMARY
  // ═══════════════════════════════════════════════
  console.log("\n" + "═".repeat(60));
  console.log(`  RESULTS: ${passed} PASSED | ${failed} FAILED | ${skipped} SKIPPED`);
  console.log("═".repeat(60) + "\n");

  if (failed > 0) process.exit(1);
}

run().catch((err) => {
  console.error("Test runner crashed:", err);
  process.exit(1);
});
