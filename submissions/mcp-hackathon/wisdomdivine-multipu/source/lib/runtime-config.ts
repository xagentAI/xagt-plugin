export const SOLANA_NETWORK = (process.env.NEXT_PUBLIC_SOLANA_NETWORK ??
  "mainnet-beta") as "devnet" | "testnet" | "mainnet-beta";

export const APP_PHASE = (process.env.NEXT_PUBLIC_APP_PHASE ??
  "mainnet") as "testnet" | "mainnet";

export const MAINNET_LAUNCH_ENABLED_PUBLIC =
  process.env.NEXT_PUBLIC_ENABLE_MAINNET_LAUNCHES !== "false";
export const EVM_LAUNCH_ADAPTERS_ENABLED_PUBLIC =
  process.env.NEXT_PUBLIC_ENABLE_EVM_LAUNCH_ADAPTERS !== "false";

export function isMainnetNetwork() {
  return SOLANA_NETWORK === "mainnet-beta";
}

export function isMainnetLaunchAllowedOnClient() {
  if (!isMainnetNetwork()) return true;
  return APP_PHASE === "mainnet" && MAINNET_LAUNCH_ENABLED_PUBLIC;
}

export function areEvmLaunchesEnabledOnClient() {
  if (APP_PHASE !== "mainnet") return true;
  return (
    MAINNET_LAUNCH_ENABLED_PUBLIC &&
    EVM_LAUNCH_ADAPTERS_ENABLED_PUBLIC
  );
}
