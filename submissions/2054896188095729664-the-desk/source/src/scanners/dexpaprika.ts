import {
  cleanString,
  compactNumber,
  fetchJson,
  makeOpportunity,
  shortError,
  toNumber,
  isKnownBlueChipSymbol,
  type ProviderScanResult,
  type ScannerOptions,
} from "./shared.js";

const provider = "dexpaprika";
const baseUrl = "https://api.dexpaprika.com";
const networks = ["ethereum", "solana", "base"];
const POOL_LIMIT = 20;

interface DexPaprikaDexes {
  dexes?: Array<{ dex_id?: string; dex_name?: string; volume_usd_24h?: number | string; txns_24h?: number | string }>;
}

interface DexPaprikaPools {
  results?: DexPaprikaPool[];
}

interface DexPaprikaPool {
  id?: string;
  dex_id?: string;
  dex_name?: string;
  chain?: string;
  liquidity_usd?: number | string;
  volume_usd_24h?: number | string;
  transactions_24h?: number | string;
  price_change_percentage_24h?: number | string;
  volume_usd?: number | string;
  transactions?: number | string;
  price_usd?: number | string;
  last_price_change_usd_24h?: number | string;
  created_at?: string;
  pool_created_at?: string;
  tokens?: DexPaprikaToken[];
}

interface DexPaprikaPoolDetail extends DexPaprikaPool {
  token_reserves?: Array<{ token_id?: string; reserve_usd?: number | string; last_price_usd?: number | string; token?: DexPaprikaToken }>;
  "24h"?: {
    volume_usd?: number | string;
    txns?: number | string;
    buys?: number | string;
    sells?: number | string;
    buy_txns?: number | string;
    sell_txns?: number | string;
    buy_count?: number | string;
    sell_count?: number | string;
    last_price_usd_change?: number | string;
  };
}

interface DexPaprikaToken {
  id?: string;
  name?: string;
  symbol?: string;
}

export async function fetchDexPaprikaOpportunities(options: ScannerOptions = {}): Promise<ProviderScanResult> {
  const networkResults = await Promise.allSettled(networks.map((network) => fetchNetwork(network, options)));
  const errors = networkResults
    .filter((result): result is PromiseRejectedResult => result.status === "rejected")
    .map((result) => shortError(result.reason));
  const opportunities = networkResults
    .filter((result): result is PromiseFulfilledResult<Awaited<ReturnType<typeof fetchNetwork>>> => result.status === "fulfilled")
    .flatMap((result) => result.value);

  const ok = opportunities.length > 0;
  return {
    ok,
    opportunities,
    mode: ok ? "live" : "degraded",
    reason: ok ? undefined : errors[0] ?? "DexPaprika returned no top pools",
    sourceHealth: [
      {
        name: "DexPaprika",
        ok,
        command: networks
          .map(
            (network) =>
              `${baseUrl}/networks/${network}/dexes + /pools/search?limit=${POOL_LIMIT}&order_by=volume_usd_24h&sort=desc`,
          )
          .join(" | "),
        error: ok ? undefined : errors[0] ?? "no rows",
        detail: errors.length > 0 ? errors.join(" | ") : undefined,
      },
    ],
  };
}

async function fetchNetwork(network: string, options: ScannerOptions) {
  const dexes = await fetchJson<DexPaprikaDexes>(`${baseUrl}/networks/${network}/dexes`, options);
  const pools = await fetchJson<DexPaprikaPools>(
    `${baseUrl}/networks/${network}/pools/search?limit=${POOL_LIMIT}&order_by=volume_usd_24h&sort=desc`,
    options,
  );
  const topDex = dexes.dexes?.[0];
  const details = await Promise.all(
    (pools.results ?? []).slice(0, POOL_LIMIT).map(async (pool) => {
      if (!pool.id) return { pool, detail: null as DexPaprikaPoolDetail | null };
      try {
        const detail = await fetchJson<DexPaprikaPoolDetail>(`${baseUrl}/networks/${network}/pools/${encodeURIComponent(pool.id)}`, options);
        return { pool, detail };
      } catch {
        return { pool, detail: null as DexPaprikaPoolDetail | null };
      }
    }),
  );

  return details
    .map(({ pool, detail }) => normalizePool(network, pool, detail, topDex?.dex_name))
    .filter((opportunity): opportunity is NonNullable<ReturnType<typeof normalizePool>> => Boolean(opportunity));
}

function normalizePool(network: string, pool: DexPaprikaPool, detail: DexPaprikaPoolDetail | null, topDexName?: string) {
  const tokens = detail?.tokens ?? pool.tokens ?? [];
  const displayToken = pickDisplayToken(tokens, detail);
  const quoteToken = tokens.find((token) => token.id !== displayToken?.id);
  const tokenAddress = displayToken?.id ?? pool.id;
  if (!tokenAddress) return null;
  const liquidityUsd = liquidityFromDetail(detail) ?? toNumber(pool.liquidity_usd);
  const h24 = detail?.["24h"];
  const volumeUsd = toNumber(h24?.volume_usd) ?? toNumber(pool.volume_usd_24h) ?? toNumber(pool.volume_usd);
  const txns = toNumber(h24?.txns) ?? toNumber(pool.transactions_24h) ?? toNumber(pool.transactions);
  const buys = firstNumber(h24?.buys, h24?.buy_txns, h24?.buy_count);
  const sells = firstNumber(h24?.sells, h24?.sell_txns, h24?.sell_count);
  const priceChangePct =
    toNumber(h24?.last_price_usd_change) ?? toNumber(pool.price_change_percentage_24h) ?? toNumber(pool.last_price_change_usd_24h);
  const priceUsd = toNumber(detail?.token_reserves?.find((reserve) => reserve.token?.id === displayToken?.id)?.last_price_usd) ?? toNumber(pool.price_usd);
  const dexName = cleanString(pool.dex_name) ?? topDexName ?? "top DEX";
  const poolCreatedAt = detail?.pool_created_at ?? detail?.created_at ?? pool.pool_created_at ?? pool.created_at;

  return makeOpportunity({
    provider,
    evidenceSkill: "dexpaprika-pools",
    tokenAddress,
    chain: network,
    symbol: displayToken?.symbol,
    name: displayToken?.name,
    source: "DexPaprika",
    externalId: pool.id,
    baseSymbol: displayToken?.symbol,
    quoteSymbol: quoteToken?.symbol,
    metrics: {
      priceUsd,
      liquidityUsd,
      volumeUsd,
      priceChangePct,
      buyTxCount1h: buys,
      sellTxCount1h: sells,
    },
    signal: {
      poolCreatedAt,
    },
    evidenceSummary: `${dexName} pool live on DexPaprika with $${compactNumber(liquidityUsd)} liquidity, $${compactNumber(volumeUsd)} 24h volume, ${txns ?? "n/a"} txns.`,
    freshness: "live DexPaprika top-pool snapshot",
  });
}

function pickDisplayToken(tokens: DexPaprikaToken[], detail: DexPaprikaPoolDetail | null) {
  const enriched = tokens.map((token) => {
    const reserve = detail?.token_reserves?.find((item) => item.token_id === token.id || item.token?.id === token.id);
    return { ...token, reserveUsd: toNumber(reserve?.reserve_usd) ?? 0 };
  });
  return (
    enriched.find((token) => token.symbol && !isKnownBlueChipSymbol(token.symbol)) ??
    enriched.sort((left, right) => right.reserveUsd - left.reserveUsd)[0] ??
    tokens[0]
  );
}

function liquidityFromDetail(detail: DexPaprikaPoolDetail | null) {
  const reserves = detail?.token_reserves ?? [];
  const total = reserves.reduce((sum, reserve) => sum + (toNumber(reserve.reserve_usd) ?? 0), 0);
  return total > 0 ? total : undefined;
}

function firstNumber(...values: unknown[]) {
  for (const value of values) {
    const number = toNumber(value);
    if (number !== undefined) return number;
  }
  return undefined;
}
