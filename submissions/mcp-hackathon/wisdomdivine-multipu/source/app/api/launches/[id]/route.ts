import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { getEnvironmentScope } from "@/lib/env-scope.server";

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params;
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  try {
    const isUuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);

    if (isUuid) {
      const supabase = createAdminSupabase();
      const scope = getEnvironmentScope();

      const { data: launch, error } = await supabase
        .from("launches")
        .select("*, tokens(*)")
        .eq("id", id)
        .eq("app_phase", scope.appPhase)
        .single();

      if (error || !launch) {
        return Response.json({ error: "Launch not found" }, { status: 404 });
      }

      let enrichedLaunch: any = {
        ...launch,
        price_usd: 0,
        price_native: 0,
        price_change_24h: 0,
        pair_address: launch.pool_address || null,
        chain_id: launch.network?.toLowerCase().includes("bsc") ? "bsc" : launch.network?.toLowerCase().includes("robinhood") ? "robinhood" : "solana",
        txns_24h: { buys: 0, sells: 0 },
      };

      if (launch.tokens?.mint_address) {
        try {
          const dexRes = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${launch.tokens.mint_address}`, {
            signal: AbortSignal.timeout(3500),
          });
          if (dexRes.ok) {
            const dexData = await dexRes.json();
            const pair = dexData.pairs?.[0];
            if (pair) {
              enrichedLaunch.price_usd = Number(pair.priceUsd || 0);
              enrichedLaunch.price_native = Number(pair.priceNative || 0);
              enrichedLaunch.price_change_24h = Number(pair.priceChange?.h24 || 0);
              enrichedLaunch.volume_24h = Number(pair.volume?.h24 || launch.volume_24h || 0);
              enrichedLaunch.market_cap = Number(pair.marketCap || pair.fdv || 0);
              enrichedLaunch.pair_address = pair.pairAddress || launch.pool_address;
              enrichedLaunch.chain_id = pair.chainId || enrichedLaunch.chain_id;
              enrichedLaunch.txns_24h = pair.txns?.h24 || { buys: 0, sells: 0 };
            }
          }
        } catch {
          // ignore DEX fetch failure for fresh tokens
        }
      }

      return Response.json({ launch: enrichedLaunch });
    } else {
      // Fetch public token details from DexScreener
      const dexRes = await fetch(`https://api.dexscreener.com/latest/dex/tokens/${id}`, {
        signal: AbortSignal.timeout(5000),
      });

      if (dexRes.ok) {
        const dexData = await dexRes.json();
        const pairs = dexData.pairs || [];
        const matchedPair =
          pairs.find((p: any) => ["solana", "bsc", "robinhood", "base"].includes(p.chainId?.toLowerCase())) ||
          pairs[0];

        if (matchedPair) {
          const chain = matchedPair.chainId?.toLowerCase();
          const normalizedNetwork =
            chain === "solana" ? "Solana" : chain === "bsc" ? "BSC" : chain === "robinhood" ? "Robinhood" : chain === "base" ? "Base" : "Solana";

          const publicLaunch = {
            id: id,
            launchpad: matchedPair.dexId || "dex",
            network: normalizedNetwork,
            pool_address: matchedPair.pairAddress || null,
            pair_address: matchedPair.pairAddress || null,
            chain_id: matchedPair.chainId || (chain === "bsc" ? "bsc" : "solana"),
            volume_24h: Number(matchedPair.volume?.h24 || 0),
            market_cap: Number(matchedPair.marketCap || matchedPair.fdv || 0),
            initial_liquidity: matchedPair.liquidity?.quote ? Number(matchedPair.liquidity.quote) : null,
            price_usd: Number(matchedPair.priceUsd || 0),
            price_native: Number(matchedPair.priceNative || 0),
            price_change_24h: Number(matchedPair.priceChange?.h24 || 0),
            price_change_1h: Number(matchedPair.priceChange?.h1 || 0),
            txns_24h: matchedPair.txns?.h24 || { buys: 0, sells: 0 },
            tokens: {
              id: id,
              name: matchedPair.baseToken.name,
              symbol: matchedPair.baseToken.symbol,
              mint_address: id,
              supply: "1000000000",
              decimals: 9,
              image_url:
                matchedPair.info?.imageUrl ||
                `https://api.dicebear.com/7.x/identicon/svg?seed=${matchedPair.baseToken.symbol}`,
              header_url: matchedPair.info?.header || null,
              description: matchedPair.info?.description || "",
              socials: {
                website: matchedPair.info?.websites?.[0]?.url || "",
                twitter: matchedPair.info?.socials?.find((s: any) => s.type === "twitter" || s.type === "x")?.url || "",
                telegram: matchedPair.info?.socials?.find((s: any) => s.type === "telegram")?.url || "",
              },
            },
          };
          return Response.json({ launch: publicLaunch });
        }
      }
      return Response.json({ error: "Public token details not found on DexScreener" }, { status: 404 });
    }
  } catch (err) {
    console.error("[API] GET /api/launches/[id] error:", err);
    return Response.json({ error: "Failed to fetch launch details" }, { status: 500 });
  }
}
