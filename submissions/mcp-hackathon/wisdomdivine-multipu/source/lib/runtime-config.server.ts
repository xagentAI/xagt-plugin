import "server-only";

import { getEnvironmentScope } from "@/lib/env-scope.server";

export function isMainnetLaunchAllowedOnServer() {
  const scope = getEnvironmentScope();
  if (scope.network !== "mainnet-beta") return true;
  return (
    scope.appPhase === "mainnet" &&
    process.env.ENABLE_MAINNET_LAUNCHES !== "false"
  );
}

export function getLaunchPolicyError() {
  if (isMainnetLaunchAllowedOnServer()) return null;
  return "Mainnet launches are disabled. This deployment is currently in a testnet safety phase.";
}

export function isEvmLaunchAllowedOnServer() {
  const scope = getEnvironmentScope();
  if (scope.appPhase !== "mainnet") return true;
  return (
    process.env.ENABLE_MAINNET_LAUNCHES !== "false" &&
    process.env.ENABLE_EVM_LAUNCH_ADAPTERS !== "false"
  );
}

export function getEvmLaunchPolicyError() {
  if (isEvmLaunchAllowedOnServer()) return null;
  return "EVM launches are disabled. Enable mainnet and EVM adapter gates explicitly.";
}
