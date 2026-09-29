import type { Connection } from "@solana/web3.js";
import type { LaunchConfig, LaunchResult, LaunchpadService } from "./types";

/**
 * Four.meme integration placeholder.
 * Four.meme is not a Solana launchpad and requires BNB Chain execution.
 */
export const fourmemeService: LaunchpadService = {
  name: "Four.meme",
  id: "fourmeme",

  async createLaunchTransaction(
    _connection: Connection,
    _config: LaunchConfig
  ): Promise<LaunchResult> {
    throw new Error(
      "Four.meme requires BNB Chain execution and is not yet available in this Solana transaction flow."
    );
  },

  async estimateFee(): Promise<number> {
    return 0;
  },
};
