import type { Connection } from "@solana/web3.js";
import type { LaunchConfig, LaunchResult, LaunchpadService } from "./types";

/**
 * Pons integration placeholder.
 * Pons is a Robinhood Chain meme launchpad and requires EVM execution.
 */
export const ponsService: LaunchpadService = {
  name: "Pons",
  id: "pons",

  async createLaunchTransaction(
    _connection: Connection,
    _config: LaunchConfig
  ): Promise<LaunchResult> {
    throw new Error(
      "Pons requires Robinhood Chain execution and is not available in this Solana transaction flow."
    );
  },

  async estimateFee(): Promise<number> {
    return 0;
  },
};
