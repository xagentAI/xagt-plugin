import test from "node:test";
import assert from "node:assert/strict";
import {
  clearScannerCache,
  composeOpportunityScan,
  fetchDexPaprikaOpportunities,
  fetchDexScreenerOpportunities,
  fetchGeckoTerminalOpportunities,
} from "../src/scanners/index.js";
import type { FetchLike, FetchResponseLike, ProviderScanResult } from "../src/scanners/shared.js";

test("DexScreener adapter normalizes profile and boost payloads", async () => {
  const fetchImpl: FetchLike = async (url) => {
    if (url.includes("token-profiles")) {
      return jsonResponse([
        {
          chainId: "solana",
          tokenAddress: "So11111111111111111111111111111111111111112",
          symbol: "SOLX",
          name: "Sol X",
          priceUsd: "2.5",
          liquidityUsd: "12500",
          volumeUsd: "98000",
          description: "Sol X token",
        },
      ]);
    }
    return jsonResponse([]);
  };

  const result = await fetchDexScreenerOpportunities({ fetchImpl });

  assert.equal(result.ok, true);
  assert.equal(result.opportunities[0]?.symbol, "SOLX");
  assert.equal(result.opportunities[0]?.chain, "Solana");
  assert.equal(result.opportunities[0]?.status, "ready");
  assert.equal(result.opportunities[0]?.evidence[0]?.skill, "dexscreener-profiles");
});

test("DexPaprika adapter normalizes top-pool payloads with liquidity, volume, txns, and price change", async () => {
  const requestedUrls: string[] = [];
  const fetchImpl: FetchLike = async (url) => {
    requestedUrls.push(url);
    if (url.includes("/dexes")) {
      return jsonResponse({ dexes: [{ dex_id: "uniswap_v3", dex_name: "Uniswap V3", volume_usd_24h: 1_000_000, txns_24h: 1200 }] });
    }
    if (url.includes("/pools/eth-pool-1")) {
      return jsonResponse({
        id: "eth-pool-1",
        tokens: [
          { id: "0xquote", symbol: "USDC", name: "USD Coin" },
          { id: "0xalpha", symbol: "ALPHA", name: "Alpha Token" },
        ],
        token_reserves: [
          { reserve_usd: "18000", last_price_usd: "1", token: { id: "0xquote", symbol: "USDC" } },
          { reserve_usd: "22000", last_price_usd: "0.42", token: { id: "0xalpha", symbol: "ALPHA" } },
        ],
        "24h": { volume_usd: "89000", txns: "630", last_price_usd_change: "7.5" },
      });
    }
    if (url.includes("/pools/search?") && url.includes("/ethereum/")) {
      return jsonResponse({
        results: [
          {
            id: "eth-pool-1",
            dex_name: "Uniswap V3",
            tokens: [
              { id: "0xquote", symbol: "USDC", name: "USD Coin" },
              { id: "0xalpha", symbol: "ALPHA", name: "Alpha Token" },
            ],
            volume_usd_24h: "70000",
            transactions_24h: "500",
            liquidity_usd: "39000",
            price_usd: "0.4",
            price_change_percentage_24h: "5",
          },
        ],
      });
    }
    return jsonResponse({ results: [] });
  };

  const result = await fetchDexPaprikaOpportunities({ fetchImpl });
  const opportunity = result.opportunities.find((row) => row.symbol === "ALPHA");

  assert.equal(result.ok, true);
  assert.equal(opportunity?.chain, "Ethereum");
  assert.equal(opportunity?.metrics.liquidityUsd, 40_000);
  assert.equal(opportunity?.metrics.volumeUsd, 89_000);
  assert.equal(opportunity?.metrics.priceChangePct, 7.5);
  assert.equal(opportunity?.status, "ready");
  assert.equal(requestedUrls.some((url) => url.includes("/pools?limit=20")), false);
  assert.equal(
    requestedUrls.some((url) =>
      url.includes("/networks/ethereum/pools/search?limit=20&order_by=volume_usd_24h&sort=desc"),
    ),
    true,
  );
});

test("DexPaprika adapter falls back to pool-search metrics when pool detail is unavailable", async () => {
  const fetchImpl: FetchLike = async (url) => {
    if (url.includes("/dexes")) {
      return jsonResponse({ dexes: [{ dex_id: "uniswap_v3", dex_name: "Uniswap V3" }] });
    }
    if (url.includes("/pools/eth-pool-fallback")) {
      return jsonResponse({ message: "temporarily unavailable" }, false, 503);
    }
    if (url.includes("/pools/search?") && url.includes("/ethereum/")) {
      return jsonResponse({
        results: [
          {
            id: "eth-pool-fallback",
            dex_name: "Uniswap V3",
            tokens: [
              { id: "0xquote", symbol: "USDC", name: "USD Coin" },
              { id: "0xfallback", symbol: "FALL", name: "Fallback Token" },
            ],
            volume_usd_24h: "123456",
            transactions_24h: "321",
            liquidity_usd: "45678",
            price_usd: "0.25",
            price_change_percentage_24h: "12.5",
          },
        ],
      });
    }
    return jsonResponse({ results: [] });
  };

  const result = await fetchDexPaprikaOpportunities({ fetchImpl });
  const opportunity = result.opportunities.find((row) => row.symbol === "FALL");

  assert.equal(result.ok, true);
  assert.equal(opportunity?.metrics.liquidityUsd, 45_678);
  assert.equal(opportunity?.metrics.volumeUsd, 123_456);
  assert.equal(opportunity?.metrics.priceUsd, 0.25);
  assert.equal(opportunity?.metrics.priceChangePct, 12.5);
  assert.match(opportunity?.evidence[0]?.summary ?? "", /321 txns/);
});

test("GeckoTerminal adapter normalizes trending-pool payloads", async () => {
  const fetchImpl: FetchLike = async (url) => {
    if (url.includes("/networks/eth/")) {
      return jsonResponse({
        data: [
          {
            id: "eth_pool_1",
            attributes: {
              address: "0xpool",
              name: "BETA / WETH",
              base_token_price_usd: "0.12",
              reserve_in_usd: "15000",
              volume_usd: { h24: "45600" },
              price_change_percentage: { h24: "11.2" },
              transactions: { h24: { buys: 300, sells: 120 } },
            },
            relationships: { base_token: { data: { id: "eth_0xbeta" } } },
          },
        ],
        included: [{ id: "eth_0xbeta", type: "token", attributes: { address: "0xbeta", symbol: "BETA", name: "Beta Token" } }],
      });
    }
    return jsonResponse({ data: [], included: [] });
  };

  const result = await fetchGeckoTerminalOpportunities({ fetchImpl });

  assert.equal(result.ok, true);
  assert.equal(result.opportunities[0]?.symbol, "BETA");
  assert.equal(result.opportunities[0]?.chain, "Ethereum");
  assert.equal(result.opportunities[0]?.metrics.buyTxCount1h, 300);
  assert.equal(result.opportunities[0]?.status, "ready");
});

test("composer dedupes by tokenAddress and chain and keeps the strongest row", async () => {
  clearScannerCache();
  const providerResult = (score: number, source: string): ProviderScanResult => ({
    ok: true,
    mode: "live",
    opportunities: [
      {
        id: source,
        ticketId: `opp_${source}`,
        status: "ready",
        action: "quote-buy",
        actionLabel: "Prepare quote",
        symbol: "DUP",
        chain: "Ethereum",
        chainIndex: "1",
        tokenAddress: "0xDUP",
        source,
        thesis: source,
        invalidation: "none",
        confidence: score,
        score,
        freshness: "test",
        metrics: { liquidityUsd: score * 1000, volumeUsd: score * 2000 },
        risk: { level: "low", verdict: "allow", reasons: ["ok"] },
        policy: { allowed: true, reasons: ["ok"] },
        proposedOrder: { mode: "quote-only", fromAsset: "USDC", toAsset: "DUP", amountUsd: 25, slippageBps: 100, quoteStatus: "not-quoted" },
        evidence: [{ source, skill: source, summary: source }],
      },
    ],
    sourceHealth: [{ name: source, ok: true, command: source }],
  });

  const scan = await composeOpportunityScan({
    providers: [
      { name: "left", fetchOpportunities: async () => providerResult(41, "left") },
      { name: "right", fetchOpportunities: async () => providerResult(88, "right") },
    ],
  });

  assert.equal(scan.opportunities.length, 1);
  assert.equal(scan.opportunities[0]?.score, 88);
  assert.match(scan.opportunities[0]?.source ?? "", /right/);
});

test("composer falls back to fixtures when every provider throws", async () => {
  clearScannerCache();
  const scan = await composeOpportunityScan({
    providers: [
      { name: "dexscreener", fetchOpportunities: async () => { throw new Error("blocked"); } },
      { name: "geckoterminal", fetchOpportunities: async () => { throw new Error("tls"); } },
      { name: "dexpaprika", fetchOpportunities: async () => { throw new Error("down"); } },
    ],
  });

  assert.equal(scan.mode, "fixture-fallback");
  assert.equal(scan.sourceMode, "demo-snapshot");
  assert.equal(scan.defaultClusterIds.length >= 5, true);
  assert.equal(scan.opportunities.every((row) => row.evidence.some((item) => item.skill === "deterministic-demo-snapshot")), true);
});

test("composer uses live mode when at least one provider succeeds", async () => {
  clearScannerCache();
  const scan = await composeOpportunityScan({
    providers: [
      { name: "dexscreener", fetchOpportunities: async () => ({ ok: false, mode: "degraded", opportunities: [], sourceHealth: [{ name: "DexScreener", ok: false, command: "x", error: "blocked" }] }) },
      { name: "geckoterminal", fetchOpportunities: async () => liveProvider("GeckoTerminal") },
    ],
  });

  assert.notEqual(scan.mode, "fixture-fallback");
  assert.equal(scan.opportunities[0]?.symbol, "LIVE");
});

test("composer cache prevents repeated upstream calls inside the TTL", async () => {
  clearScannerCache();
  let calls = 0;
  const providers = [
    {
      name: "dexpaprika",
      fetchOpportunities: async () => {
        calls += 1;
        return liveProvider("DexPaprika");
      },
    },
  ];

  await composeOpportunityScan({ providers, ttlMs: 30_000 });
  const second = await composeOpportunityScan({ providers, ttlMs: 30_000 });

  assert.equal(calls, 1);
  assert.equal(second.sourceHealth[0]?.cached, true);
});

function liveProvider(name: string): ProviderScanResult {
  const symbols = ["LIVE", "SCOUT", "RADAR"];
  return {
    ok: true,
    mode: "live",
    opportunities: symbols.map((symbol, index) => ({
        id: `live-${index}`,
        ticketId: `opp_live_${index}`,
        status: "ready",
        action: "quote-buy",
        actionLabel: "Prepare quote",
        symbol,
        chain: "Base",
        chainIndex: "8453",
        tokenAddress: `0xlive${index}`,
        source: name,
        thesis: "live provider",
        invalidation: "none",
        confidence: 70,
        score: 70,
        freshness: "test",
        metrics: { liquidityUsd: 20_000 + index, volumeUsd: 40_000 + index },
        risk: { level: "low", verdict: "allow", reasons: ["ok"] },
        policy: { allowed: true, reasons: ["ok"] },
        proposedOrder: { mode: "quote-only", fromAsset: "USDC", toAsset: symbol, amountUsd: 25, slippageBps: 100, quoteStatus: "not-quoted" },
        evidence: [{ source: name, skill: name.toLowerCase(), summary: "live" }],
      })),
    sourceHealth: [{ name, ok: true, command: name }],
  };
}

function jsonResponse(data: unknown, ok = true, status = 200): FetchResponseLike {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "ERROR",
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}
