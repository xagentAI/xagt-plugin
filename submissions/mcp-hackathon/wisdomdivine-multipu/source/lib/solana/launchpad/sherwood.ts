import type { Connection } from "@solana/web3.js";
import type { LaunchConfig, LaunchResult, LaunchpadService } from "./types";

/**
 * Sherwood integration placeholder.
 * Sherwood is not a Solana launchpad and requires Robinhood Chain execution.
 */
export const sherwoodService: LaunchpadService = {
  name: "Sherwood",
  id: "sherwood",

  async createLaunchTransaction(
    _connection: Connection,
    _config: LaunchConfig
  ): Promise<LaunchResult> {
    throw new Error(
      "Sherwood requires Robinhood Chain execution and is not available in this Solana transaction flow."
    );
  },

  async estimateFee(): Promise<number> {
    return 0;
  },
};
