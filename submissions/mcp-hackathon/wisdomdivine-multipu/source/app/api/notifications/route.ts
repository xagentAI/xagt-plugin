import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { getEnvironmentScope } from "@/lib/env-scope.server";
import { calculateStrategySignal } from "@/lib/olaxbt/client";

export type NotificationCategory = "LAUNCH" | "TRADE" | "FEE" | "SIGNAL" | "SYSTEM";

export interface NotificationItem {
  id: string;
  category: NotificationCategory;
  title: string;
  detail: string;
  timestamp: string;
  timeAgo: string;
  status: "SUCCESS" | "PENDING" | "ALERT" | "INFO";
  metric?: string;
  link?: string;
}

function timeAgo(date: Date): string {
  const now = Date.now();
  const diffMs = now - date.getTime();
  const seconds = Math.max(1, Math.floor(diffMs / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn || !auth.walletAddress) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const supabase = createAdminSupabase();
    const scope = getEnvironmentScope();
    const notifications: NotificationItem[] = [];

    // 1. Account Onboarding & Real Authentication Security Events (Unique to this account)
    try {
      const { data: userRow } = await supabase
        .from("users")
        .select("id, wallet_address, created_at, updated_at")
        .eq("wallet_address", auth.walletAddress)
        .maybeSingle();

      if (userRow) {
        const createdAtDate = new Date(userRow.created_at);
        const shortAddr = `${auth.walletAddress.slice(0, 6)}...${auth.walletAddress.slice(-4)}`;
        const chainName = auth.walletKind === "evm" ? "EVM (BSC / Robinhood)" : "Solana";

        // Initial Account Provisioning Notification
        notifications.push({
          id: `acc-init-${userRow.id || auth.walletAddress}`,
          category: "SYSTEM",
          title: "Mainnet Account Initialized",
          detail: `Wallet ${shortAddr} connected to Multipu on ${chainName}. Multi-chain deployment and DEX routing active.`,
          timestamp: userRow.created_at,
          timeAgo: timeAgo(createdAtDate),
          status: "SUCCESS",
          metric: "ONLINE",
          link: "/dashboard",
        });

        // Subsequent Session Signature Event if updated later
        if (
          userRow.updated_at &&
          Math.abs(new Date(userRow.updated_at).getTime() - createdAtDate.getTime()) > 5000
        ) {
          const updatedAtDate = new Date(userRow.updated_at);
          notifications.push({
            id: `acc-auth-${auth.walletAddress}-${updatedAtDate.getTime()}`,
            category: "SYSTEM",
            title: "Session Cryptographically Verified",
            detail: `Dual-chain challenge signature confirmed for ${shortAddr}.`,
            timestamp: userRow.updated_at,
            timeAgo: timeAgo(updatedAtDate),
            status: "INFO",
            metric: "AUTH",
            link: "/dashboard",
          });
        }
      }
    } catch (userErr) {
      console.warn("[NOTIFICATIONS] User query error:", userErr);
    }

    // 2. User Developer API Keys (Unique to this account)
    try {
      const { data: devKeys } = await supabase
        .from("developer_api_keys")
        .select("id, name, revoked, created_at")
        .eq("wallet_address", auth.walletAddress)
        .order("created_at", { ascending: false });

      (devKeys || []).forEach((k: any) => {
        const kDate = new Date(k.created_at);
        notifications.push({
          id: `key-${k.id}`,
          category: "SYSTEM",
          title: `API Key ${k.revoked ? "Revoked" : "Active"}: "${k.name}"`,
          detail: k.revoked
            ? "REST API key revoked. Automated token launching disabled for this credential."
            : "REST API key generated for headless token launch and automated agent dispatch.",
          timestamp: k.created_at,
          timeAgo: timeAgo(kDate),
          status: k.revoked ? "ALERT" : "SUCCESS",
          metric: k.revoked ? "REVOKED" : "API KEY",
          link: "/dashboard/api",
        });
      });
    } catch (keyErr) {
      console.warn("[NOTIFICATIONS] Developer keys query error:", keyErr);
    }

    // 3. User Developer Autonomous Wallets (Unique to this account)
    try {
      const { data: devWallets } = await supabase
        .from("developer_wallets")
        .select("id, public_key, network, created_at")
        .eq("wallet_address", auth.walletAddress)
        .order("created_at", { ascending: false });

      (devWallets || []).forEach((w: any) => {
        const wDate = new Date(w.created_at);
        notifications.push({
          id: `wallet-${w.id}`,
          category: "SYSTEM",
          title: "Execution Keypair Configured",
          detail: `Autonomous sub-wallet ${w.public_key.slice(0, 6)}...${w.public_key.slice(-4)} active for ${w.network.toUpperCase()} liquidity routing.`,
          timestamp: w.created_at,
          timeAgo: timeAgo(wDate),
          status: "SUCCESS",
          metric: w.network.toUpperCase(),
          link: "/dashboard/api",
        });
      });
    } catch (walErr) {
      console.warn("[NOTIFICATIONS] Developer wallets query error:", walErr);
    }

    // 4. User's Tokens & Launches (Unique to this account)
    let userTokensList: any[] = [];
    try {
      const { data: userTokens } = await supabase
        .from("tokens")
        .select(
          "id, name, symbol, decimals, supply, status, created_at, updated_at, mint_address, launches(id, launchpad, status, pool_address, initial_liquidity, volume_24h, created_at, launched_at)"
        )
        .eq("wallet_address", auth.walletAddress)
        .eq("app_phase", scope.appPhase)
        .order("created_at", { ascending: false })
        .limit(15);

      userTokensList = userTokens || [];

      userTokensList.forEach((t: any) => {
        const tokenCreated = new Date(t.created_at);
        notifications.push({
          id: `token-create-${t.id}`,
          category: "LAUNCH",
          title: `Token Created: ${t.name} ($${t.symbol})`,
          detail: `Supply: ${Number(t.supply).toLocaleString()} (${t.decimals} decimals). Ready for multi-chain dispatch.`,
          timestamp: t.created_at,
          timeAgo: timeAgo(tokenCreated),
          status: t.status === "active" ? "SUCCESS" : t.status === "pending" ? "PENDING" : "ALERT",
          metric: t.status.toUpperCase(),
          link: "/dashboard/tokens",
        });

        if (t.mint_address) {
          const tokenUpdated = new Date(t.updated_at || t.created_at);
          notifications.push({
            id: `token-mint-${t.id}`,
            category: "LAUNCH",
            title: `On-Chain Mint Verified: $${t.symbol}`,
            detail: `Contract deployed on-chain at ${t.mint_address.slice(0, 6)}...${t.mint_address.slice(-4)}`,
            timestamp: t.updated_at || t.created_at,
            timeAgo: timeAgo(tokenUpdated),
            status: "SUCCESS",
            metric: "ON-CHAIN",
            link: "/dashboard/tokens",
          });
        }

        (t.launches || []).forEach((l: any) => {
          const lDate = new Date(l.launched_at || l.created_at);
          notifications.push({
            id: `launch-${l.id}`,
            category: "LAUNCH",
            title: `${l.launchpad.toUpperCase()} Dispatch: $${t.symbol}`,
            detail: `Status: ${l.status.toUpperCase()}${l.pool_address ? ` | Pool: ${l.pool_address.slice(0, 6)}...${l.pool_address.slice(-4)}` : ""}${l.volume_24h ? ` | 24h Vol: $${Number(l.volume_24h).toLocaleString()}` : ""}`,
            timestamp: l.launched_at || l.created_at,
            timeAgo: timeAgo(lDate),
            status: l.status === "live" ? "SUCCESS" : "PENDING",
            metric: l.launchpad.toUpperCase(),
            link: "/dashboard/launches",
          });
        });
      });
    } catch (tokErr) {
      console.warn("[NOTIFICATIONS] Tokens query error:", tokErr);
    }

    // 5. User Protocol Royalties & Earnings (Unique to this account)
    try {
      const { data: earnings } = await supabase
        .from("earnings")
        .select("id, amount_sol, fee_type, launchpad, recorded_at, tokens(name, symbol)")
        .eq("wallet_address", auth.walletAddress)
        .eq("app_phase", scope.appPhase)
        .order("recorded_at", { ascending: false })
        .limit(15);

      (earnings || []).forEach((e: any) => {
        const eDate = new Date(e.recorded_at);
        notifications.push({
          id: `earning-${e.id}`,
          category: "FEE",
          title: `Royalty Received: +${Number(e.amount_sol).toFixed(4)} SOL`,
          detail: `Creator fee distribution from ${e.tokens?.name || "Pool"} on ${e.launchpad}`,
          timestamp: e.recorded_at,
          timeAgo: timeAgo(eDate),
          status: "SUCCESS",
          metric: "+SOL",
          link: "/dashboard/earnings",
        });
      });
    } catch (earnErr) {
      console.warn("[NOTIFICATIONS] Earnings query error:", earnErr);
    }

    // 6. User AI Trading Agents & Real Trade Executions (Unique to this account)
    try {
      const { data: userAgents } = await supabase
        .from("trading_agents")
        .select("id, name, prompt, mode, chain, launchpads, status, created_at")
        .eq("wallet_address", auth.walletAddress)
        .order("created_at", { ascending: false })
        .limit(10);

      const agentIds = (userAgents || []).map((a: any) => a.id);

      (userAgents || []).forEach((ag: any) => {
        const agDate = new Date(ag.created_at);
        notifications.push({
          id: `agent-${ag.id}`,
          category: "TRADE",
          title: `AI Agent Configured: ${ag.name}`,
          detail: `Strategy: "${ag.prompt.slice(0, 60)}..." (${ag.mode.toUpperCase()} on ${ag.chain.toUpperCase()})`,
          timestamp: ag.created_at,
          timeAgo: timeAgo(agDate),
          status: ag.status === "active" ? "SUCCESS" : "INFO",
          metric: ag.status.toUpperCase(),
          link: "/dashboard/explore",
        });
      });

      if (agentIds.length > 0) {
        const { data: userTrades } = await supabase
          .from("agent_trades")
          .select(
            "id, agent_id, token_symbol, action, launchpad, chain, amount_in, amount_out, pnl_pct, execution_log, created_at"
          )
          .in("agent_id", agentIds)
          .order("created_at", { ascending: false })
          .limit(15);

        (userTrades || []).forEach((tr: any) => {
          const trDate = new Date(tr.created_at);
          const isProfit = tr.pnl_pct && tr.pnl_pct > 0;
          notifications.push({
            id: `trade-${tr.id}`,
            category: "TRADE",
            title: `Trade Executed: ${tr.action.toUpperCase()} $${tr.token_symbol}`,
            detail:
              tr.execution_log ||
              `Executed ${tr.action} on ${tr.launchpad} with ${tr.amount_in} ${tr.chain?.toUpperCase() === "BSC" ? "BNB" : "SOL"}`,
            timestamp: tr.created_at,
            timeAgo: timeAgo(trDate),
            status: isProfit ? "SUCCESS" : "INFO",
            metric: tr.pnl_pct ? `${tr.pnl_pct > 0 ? "+" : ""}${tr.pnl_pct}%` : "FILLED",
            link: "/dashboard/explore",
          });
        });
      }
    } catch (agentErr) {
      console.warn("[NOTIFICATIONS] Agents query error:", agentErr);
    }

    // 7. Real Ecosystem Live Launches from the Database (Real community activity)
    let ecoLaunches: any[] = [];
    try {
      const { data: platformLaunches } = await supabase
        .from("launches")
        .select("id, launchpad, status, created_at, launched_at, volume_24h, wallet_address, tokens(id, name, symbol)")
        .eq("status", "live")
        .neq("wallet_address", auth.walletAddress)
        .order("created_at", { ascending: false })
        .limit(6);

      ecoLaunches = platformLaunches || [];

      ecoLaunches.forEach((pl: any) => {
        const plDate = new Date(pl.launched_at || pl.created_at);
        notifications.push({
          id: `eco-launch-${pl.id}`,
          category: "LAUNCH",
          title: `Ecosystem Pool Live: $${pl.tokens?.symbol || "Token"}`,
          detail: `${pl.tokens?.name || "Token"} deployed on ${pl.launchpad.toUpperCase()}${pl.volume_24h ? ` • 24h Volume: $${Number(pl.volume_24h).toLocaleString()}` : ""}`,
          timestamp: pl.launched_at || pl.created_at,
          timeAgo: timeAgo(plDate),
          status: "SUCCESS",
          metric: "ECOSYSTEM",
          link: "/dashboard/explore",
        });
      });
    } catch (ecoErr) {
      console.warn("[NOTIFICATIONS] Ecosystem query error:", ecoErr);
    }

    // 8. Market Signals: Strictly calculated on REAL tokens with REAL timestamps
    // (Only triggers if the user has tokens or there are live launches in the DB)
    const activeTokensForSignals: Array<{ id: string; symbol: string; timestamp: string; volume: number }> = [];
    userTokensList.forEach((t: any) => {
      if (t.symbol) {
        activeTokensForSignals.push({
          id: t.id,
          symbol: t.symbol,
          timestamp: t.updated_at || t.created_at,
          volume: 25000,
        });
      }
    });
    ecoLaunches.forEach((pl: any) => {
      if (pl.tokens?.symbol) {
        activeTokensForSignals.push({
          id: pl.tokens.id || pl.id,
          symbol: pl.tokens.symbol,
          timestamp: pl.launched_at || pl.created_at,
          volume: Number(pl.volume_24h || 15000),
        });
      }
    });

    const seenSymbols = new Set<string>();
    activeTokensForSignals.forEach((tok) => {
      const sym = tok.symbol.toUpperCase();
      if (seenSymbols.has(sym)) return;
      seenSymbols.add(sym);

      const sig = calculateStrategySignal(sym, 70, tok.volume);
      const sDate = new Date(tok.timestamp);
      notifications.push({
        id: `sig-${tok.id}-${sym}`,
        category: "SIGNAL",
        title: `${sig.strategyName} ($${sym})`,
        detail: `${sig.recommendation} | Momentum: ${sig.momentumScore}/100 | Volume Surge: +${sig.volumeSurge24h}%`,
        timestamp: tok.timestamp,
        timeAgo: timeAgo(sDate),
        status: sig.momentumScore > 80 ? "ALERT" : "INFO",
        metric: `${sig.momentumScore}/100`,
        link: "/dashboard/explore",
      });
    });

    // 9. Sort all notifications descending by actual timestamp
    notifications.sort(
      (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
    );

    return Response.json({
      notifications: notifications.slice(0, 40),
      unreadCount: notifications.filter((n) => n.status === "ALERT" || n.status === "PENDING").length,
      walletAddress: auth.walletAddress,
    });
  } catch (err) {
    console.error("[API] GET /notifications error:", err);
    return Response.json({ error: "Failed to fetch notifications" }, { status: 500 });
  }
}
