/**
 * Launchpad registry.
 *
 * Central access point for all launchpad services.
 * Import this instead of individual modules.
 */

import { meteoraService } from "./meteora";
import { bagsService } from "./bags";
import { pumpfunService } from "./pumpfun";
import { fourmemeService } from "./fourmeme";
import { ponsService } from "./pons";
import { sherwoodService } from "./sherwood";
import type { LaunchpadService } from "./types";

export type { LaunchConfig, LaunchResult, LaunchpadService } from "./types";

export const launchpads: Record<string, LaunchpadService> = {
  meteora: meteoraService,
  bags: bagsService,
  pumpfun: pumpfunService,
  fourmeme: fourmemeService,
  pons: ponsService,
  sherwood: sherwoodService,
};

export function getLaunchpad(id: string): LaunchpadService | null {
  return launchpads[id] || null;
}

export const LAUNCHPAD_META = [
  {
    id: "meteora" as const,
    name: "Meteora",
    description: "Dynamic liquidity pools & DLMM. Professional token launches.",
    image: "/meteora.png",
    estimatedFee: "~0.5 SOL",
    network: "Solana",
    ready: false,
  },
  {
    id: "bags" as const,
    name: "Bags",
    description: "Community-driven, meme-friendly. Built for the culture.",
    image: "/bags.png",
    estimatedFee: "~0.3 SOL",
    network: "Solana",
    ready: false,
  },
  {
    id: "pumpfun" as const,
    name: "Pump.fun",
    description: "Viral bonding curves. Instant tradability and massive reach.",
    image: "/pumpfun.png",
    estimatedFee: "~0.02 SOL",
    network: "Solana",
    ready: false,
  },
  {
    id: "fourmeme" as const,
    name: "Four.meme",
    description: "BNB Chain meme launchpad with fair-launch mechanics.",
    image: "/four-meme.png",
    estimatedFee: "~0.005 BNB",
    network: "BNB Smart Chain",
    ready: false,
  },
  {
    id: "pons" as const,
    name: "Pons",
    description: "Robinhood Chain meme launchpad featuring time-prioritized sequencing.",
    image: "/pons.png",
    estimatedFee: "~0.0001 ETH",
    network: "Robinhood Chain",
    ready: false,
  },
  {
    id: "sherwood" as const,
    name: "Sherwood",
    description: "Robinhood Chain liquidity engine for fair-launch memes.",
    image: "/pons.png",
    estimatedFee: "~0.0001 ETH",
    network: "Robinhood Chain",
    ready: false,
  },
] as const;
