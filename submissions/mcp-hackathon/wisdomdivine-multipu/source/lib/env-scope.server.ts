import "server-only";

import { APP_PHASE, SOLANA_NETWORK } from "@/lib/runtime-config";
import { createAdminSupabase } from "@/lib/supabase/server";

export interface EnvironmentScope {
  network: "devnet" | "testnet" | "mainnet-beta";
  appPhase: "testnet" | "mainnet";
}

let cachedScope: EnvironmentScope | null = null;
let cacheExpiry = 0;
const CACHE_TTL_MS = 15_000;

export async function fetchAdminPhaseOverride(): Promise<EnvironmentScope | null> {
  try {
    const supabase = createAdminSupabase();
    const { data } = await supabase
      .from("admin_settings")
      .select("value")
      .eq("key", "app_phase_override")
      .maybeSingle();

    const override = data?.value as {
      appPhase?: string;
      mainnetLaunchesEnabled?: boolean;
      evmLaunchesEnabled?: boolean;
    } | undefined;

    if (override?.appPhase === "mainnet") {
      return {
        network: "mainnet-beta",
        appPhase: "mainnet",
      };
    } else if (override?.appPhase === "testnet") {
      return {
        network: "devnet",
        appPhase: "testnet",
      };
    }
  } catch {
    // fallback to env
  }
  return null;
}

export function getEnvironmentScope(): EnvironmentScope {
  const now = Date.now();
  if (!cachedScope || now >= cacheExpiry) {
    fetchAdminPhaseOverride()
      .then((override) => {
        if (override) {
          cachedScope = override;
          cacheExpiry = Date.now() + CACHE_TTL_MS;
        }
      })
      .catch(() => {});
  }

  if (cachedScope) {
    return cachedScope;
  }

  return {
    network: SOLANA_NETWORK,
    appPhase: APP_PHASE,
  };
}

export async function resolveEnvironmentScope(): Promise<EnvironmentScope> {
  const now = Date.now();
  if (cachedScope && now < cacheExpiry) {
    return cachedScope;
  }

  const override = await fetchAdminPhaseOverride();
  if (override) {
    cachedScope = override;
    cacheExpiry = Date.now() + CACHE_TTL_MS;
    return override;
  }

  return {
    network: SOLANA_NETWORK,
    appPhase: APP_PHASE,
  };
}

