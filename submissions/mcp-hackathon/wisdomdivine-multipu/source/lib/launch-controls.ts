import "server-only";

import type { LaunchpadId } from "@/lib/supabase/database.types";
import { createAdminSupabase } from "@/lib/supabase/server";

const DEFAULT_LAUNCH_CONTROLS = {
  launchesPaused: false,
  allowlistMode: false,
  allowedWallets: [] as string[],
  launchpadsEnabled: {
    meteora: true,
    bags: true,
    pumpfun: true,
    fourmeme: true,
    pons: true,
    sherwood: true,
  } as Record<LaunchpadId, boolean>,
};

export type LaunchControls = typeof DEFAULT_LAUNCH_CONTROLS;

function asBoolean(value: unknown, fallback: boolean) {
  return typeof value === "boolean" ? value : fallback;
}

function asWalletList(value: unknown) {
  if (!Array.isArray(value)) return [];
  return value
    .filter((entry): entry is string => typeof entry === "string")
    .map((wallet) => wallet.trim())
    .filter(Boolean);
}

function asLaunchpadState(value: unknown): Record<LaunchpadId, boolean> {
  const state: Record<LaunchpadId, boolean> = { ...DEFAULT_LAUNCH_CONTROLS.launchpadsEnabled };
  if (!value || typeof value !== "object") return state;
  const input = value as Record<string, unknown>;
  for (const launchpad of Object.keys(state) as LaunchpadId[]) {
    state[launchpad] = asBoolean(input[launchpad], state[launchpad]);
  }
  return state;
}

function normalizeLaunchControls(value: unknown): LaunchControls {
  if (!value || typeof value !== "object") return { ...DEFAULT_LAUNCH_CONTROLS };
  const input = value as Record<string, unknown>;
  return {
    launchesPaused: asBoolean(
      input.launchesPaused,
      DEFAULT_LAUNCH_CONTROLS.launchesPaused
    ),
    allowlistMode: asBoolean(
      input.allowlistMode,
      DEFAULT_LAUNCH_CONTROLS.allowlistMode
    ),
    allowedWallets: asWalletList(input.allowedWallets),
    launchpadsEnabled: asLaunchpadState(input.launchpadsEnabled),
  };
}

/**
 * Reads the latest launch controls from Supabase admin_settings.
 * Used by launch creation route to enforce platform pause, whitelist, and adapter toggles.
 */
export async function getLaunchControls(): Promise<LaunchControls> {
  try {
    const supabase = createAdminSupabase();
    const { data, error } = await supabase
      .from("admin_settings")
      .select("value")
      .eq("key", "launch_controls")
      .maybeSingle();

    if (error) {
      console.error("[launch-controls] Query failed, failing closed:", error);
      return {
        ...DEFAULT_LAUNCH_CONTROLS,
        launchesPaused: true,
      };
    }

    return normalizeLaunchControls(data?.value);
  } catch (err) {
    console.error("[launch-controls] Failed to read launch controls, failing closed:", err);
    return {
      ...DEFAULT_LAUNCH_CONTROLS,
      launchesPaused: true,
    };
  }
}
