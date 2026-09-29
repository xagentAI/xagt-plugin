/**
 * Signal & Strip sellable ad inventory.
 *
 * STUB STATUS: This is STATIC DATA, not a live inventory system.
 * - Prices reflect the sponsor ladder approved for Muse Hall / Signal & Strip.
 * - `status` is hardcoded to "available" — there is no real availability
 *   tracking, no double-booking protection, and no connection to any
 *   booking or payment system.
 * - Descriptions are DRAFT marketing copy, not final specs.
 * Before any public deployment, replace this with a real inventory source
 * (database or API) and real availability checks.
 */

export type InventoryCategory =
  | "booth"
  | "signage"
  | "digital"
  | "naming"
  | "experiential";

export interface InventoryItem {
  id: string;
  name: string;
  category: InventoryCategory;
  /** Price in USDC. */
  price_usdc: number;
  /** Billing unit, e.g. "per event". Draft — confirm before selling. */
  unit: string;
  /** Draft description. */
  description: string;
  /** STUB: always "available" until a real inventory backend exists. */
  status: "available" | "sold" | "reserved";
}

export const INVENTORY: InventoryItem[] = [
  // ---- Expo booths (Arena Tower L3) ----
  {
    id: "booth-ax1",
    name: "Expo Booth AX1",
    category: "booth",
    price_usdc: 5,
    unit: "per event",
    description:
      "DRAFT: Standard expo booth on the Arena Tower expo floor. Branding on booth signage, live in the 3D venue.",
    status: "available",
  },
  {
    id: "booth-ax2",
    name: "Expo Booth AX2",
    category: "booth",
    price_usdc: 5,
    unit: "per event",
    description:
      "DRAFT: Standard expo booth on the Arena Tower expo floor. Branding on booth signage, live in the 3D venue.",
    status: "available",
  },
  {
    id: "booth-ax3",
    name: "Expo Booth AX3",
    category: "booth",
    price_usdc: 5,
    unit: "per event",
    description:
      "DRAFT: Standard expo booth on the Arena Tower expo floor. Branding on booth signage, live in the 3D venue.",
    status: "available",
  },
  {
    id: "booth-ax4",
    name: "Expo Booth AX4",
    category: "booth",
    price_usdc: 5,
    unit: "per event",
    description:
      "DRAFT: Standard expo booth on the Arena Tower expo floor. Branding on booth signage, live in the 3D venue.",
    status: "available",
  },
  {
    id: "booth-ax5",
    name: "Expo Booth AX5",
    category: "booth",
    price_usdc: 5,
    unit: "per event",
    description:
      "DRAFT: Standard expo booth on the Arena Tower expo floor. Branding on booth signage, live in the 3D venue.",
    status: "available",
  },
  {
    id: "booth-ax6",
    name: "Expo Booth AX6",
    category: "booth",
    price_usdc: 5,
    unit: "per event",
    description:
      "DRAFT: Standard expo booth on the Arena Tower expo floor. Branding on booth signage, live in the 3D venue.",
    status: "available",
  },

  // ---- Sponsor ladder ----
  {
    id: "sponsor-food-stall",
    name: "Food Stall Sponsorship",
    category: "experiential",
    price_usdc: 8,
    unit: "per event",
    description:
      "DRAFT: Brand presence at a food stall activation during the event.",
    status: "available",
  },
  {
    id: "sponsor-floor-decal",
    name: "Floor Decal",
    category: "signage",
    price_usdc: 10,
    unit: "per event",
    description:
      "DRAFT: Branded floor decal in a high-foot-traffic zone of the venue.",
    status: "available",
  },
  {
    id: "sponsor-escalator",
    name: "Escalator Wrap",
    category: "signage",
    price_usdc: 12,
    unit: "per event",
    description:
      "DRAFT: Branded wrap on escalator panels between floors.",
    status: "available",
  },
  {
    id: "sponsor-atrium-skybridge",
    name: "Atrium / Skybridge Banner",
    category: "signage",
    price_usdc: 15,
    unit: "per event",
    description:
      "DRAFT: Hanging banner in the atrium or across the skybridge.",
    status: "available",
  },
  {
    id: "sponsor-facade",
    name: "Facade Banner",
    category: "signage",
    price_usdc: 20,
    unit: "per event",
    description:
      "DRAFT: Banner placement on the building facade, visible from the approach.",
    status: "available",
  },
  {
    id: "sponsor-ribbon",
    name: "LED Ribbon",
    category: "digital",
    price_usdc: 20,
    unit: "per event",
    description:
      "DRAFT: Rotating placement on the arena LED ribbon boards.",
    status: "available",
  },
  {
    id: "sponsor-billboard",
    name: "Outdoor Billboard",
    category: "signage",
    price_usdc: 25,
    unit: "per event",
    description:
      "DRAFT: Placement on the outdoor billboard facing event traffic.",
    status: "available",
  },
  {
    id: "sponsor-keynote-led",
    name: "Keynote LED Wall",
    category: "digital",
    price_usdc: 35,
    unit: "per event",
    description:
      "DRAFT: Spot on the keynote LED video wall during main-stage programming.",
    status: "available",
  },
  {
    id: "sponsor-jumbotron",
    name: "Jumbotron (JB1)",
    category: "digital",
    price_usdc: 40,
    unit: "per event",
    description:
      "DRAFT: Jumbotron placement inside the arena bowl, visible to the full crowd.",
    status: "available",
  },
  {
    id: "sponsor-stage-backdrop",
    name: "Stage Backdrop",
    category: "digital",
    price_usdc: 50,
    unit: "per event",
    description:
      "DRAFT: Brand on the main stage backdrop during headline programming.",
    status: "available",
  },
  {
    id: "sponsor-facade-wrap",
    name: "Facade Wrap",
    category: "signage",
    price_usdc: 75,
    unit: "per event",
    description:
      "DRAFT: Full-building facade wrap — maximum exterior visibility.",
    status: "available",
  },
  {
    id: "sponsor-arena-naming",
    name: "Arena Naming Rights",
    category: "naming",
    price_usdc: 150,
    unit: "per event",
    description:
      "DRAFT: Top-tier placement — the arena carries your name for the event.",
    status: "available",
  },
];

export function findInventoryItem(id: string): InventoryItem | undefined {
  return INVENTORY.find((item) => item.id === id);
}
