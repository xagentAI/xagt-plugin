/**
 * Signal & Strip MCP server definition.
 *
 * Exposes the ad-network tools over MCP. Transport wiring lives in index.ts;
 * this module builds a fresh McpServer per request (stateless mode).
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";
import {
  createBookingIntent,
  getBooking,
} from "./bookings.js";
import { INVENTORY, findInventoryItem } from "./inventory.js";

const CATEGORY_VALUES = [
  "booth",
  "signage",
  "digital",
  "naming",
  "experiential",
] as const;

function paymentInstructions(bookingId?: string) {
  const treasury =
    process.env.SIGNAL_STRIP_TREASURY_WALLET?.trim() || null;
  return {
    currency: "USDC",
    network: "Base",
    chain_id: 8453,
    treasury_wallet: treasury,
    treasury_wallet_status: treasury
      ? "configured"
      : "STUB — no treasury wallet configured. Set SIGNAL_STRIP_TREASURY_WALLET before accepting real payments.",
    ...(bookingId ? { payment_memo: bookingId } : {}),
    steps: [
      "Send the exact USDC amount on the Base network to the treasury wallet above.",
      bookingId
        ? `Include your booking ID (${bookingId}) in the transaction memo/note so the payment can be matched.`
        : "Include your booking ID in the transaction memo/note so the payment can be matched.",
      "STUB: Payment is NOT verified automatically by this server. A human from Signal & Strip confirms receipt and marks the booking confirmed.",
    ],
    disclaimer:
      "STUB: This server never touches private keys and captures no payment. All payments happen off-band in the buyer's own wallet.",
  };
}

export function createSignalStripServer(): McpServer {
  const server = new McpServer({
    name: "signal-strip",
    version: "0.1.0",
  });

  server.tool(
    "list_inventory",
    "List all sellable Signal & Strip advertising slots with prices (USDC). STUB: inventory is static data; availability is not tracked live.",
    {
      category: z
        .enum(CATEGORY_VALUES)
        .optional()
        .describe(
          "Optional filter: booth | signage | digital | naming | experiential"
        ),
    },
    async ({ category }) => {
      const items = category
        ? INVENTORY.filter((i) => i.category === category)
        : INVENTORY;
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              {
                stub_notice:
                  "Static inventory data. Prices in USDC. Availability is NOT tracked live — every item shows 'available' until a real inventory backend is wired up.",
                count: items.length,
                items,
              },
              null,
              2
            ),
          },
        ],
      };
    }
  );

  server.tool(
    "get_package_details",
    "Get full details for one ad package by its package ID (use list_inventory to find IDs). STUB: descriptions are draft copy, not final specs.",
    {
      package_id: z
        .string()
        .describe("The package ID, e.g. 'sponsor-jumbotron' or 'booth-ax1'"),
    },
    async ({ package_id }) => {
      const item = findInventoryItem(package_id);
      if (!item) {
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                {
                  error: `Unknown package_id '${package_id}'.`,
                  hint: "Call list_inventory to see valid package IDs.",
                },
                null,
                2
              ),
            },
          ],
          isError: true,
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              {
                stub_notice:
                  "Draft package details. Specs and durations are placeholders — confirm with Signal & Strip before selling.",
                package: item,
                payment: paymentInstructions(),
              },
              null,
              2
            ),
          },
        ],
      };
    }
  );

  server.tool(
    "book_slot",
    "Create a BOOKING INTENT for an ad slot. IMPORTANT: this does NOT capture payment and does NOT guarantee the slot — it records intent only (status: pending_payment). A human from Signal & Strip must confirm after receiving USDC off-band.",
    {
      package_id: z
        .string()
        .describe("The package ID from list_inventory."),
      buyer_handle: z
        .string()
        .min(1)
        .describe(
          "Buyer's handle/identifier (e.g. X handle or agent name)."
        ),
      buyer_contact: z
        .string()
        .optional()
        .describe("Optional contact info (e.g. email or DM handle)."),
      notes: z.string().optional().describe("Optional notes for the order."),
    },
    async ({ package_id, buyer_handle, buyer_contact, notes }) => {
      const item = findInventoryItem(package_id);
      if (!item) {
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                {
                  error: `Unknown package_id '${package_id}'.`,
                  hint: "Call list_inventory to see valid package IDs.",
                },
                null,
                2
              ),
            },
          ],
          isError: true,
        };
      }
      const intent = createBookingIntent({
        package_id: item.id,
        package_name: item.name,
        price_usdc: item.price_usdc,
        buyer_handle,
        buyer_contact,
        notes,
      });
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(
              {
                stub_notice:
                  "INTENT ONLY. No payment captured, slot NOT reserved in any real system. Stored in local data/bookings.json. A human must confirm after off-band USDC receipt.",
                booking: intent,
                next_steps: [
                  `Send exactly ${item.price_usdc} USDC on Base — see get_payment_instructions (include booking ID ${intent.booking_id} in the memo).`,
                  "Signal & Strip confirms receipt manually and flips the booking to confirmed.",
                ],
              },
              null,
              2
            ),
          },
        ],
      };
    }
  );

  server.tool(
    "get_booking_status",
    "Look up a booking intent by its booking ID. STUB: reads the local JSON file; statuses are only ever 'pending_payment' unless a human edits the file.",
    {
      booking_id: z
        .string()
        .describe("The booking ID returned by book_slot, e.g. 'ss-xxxxxxxx'."),
    },
    async ({ booking_id }) => {
      const booking = getBooking(booking_id);
      if (!booking) {
        return {
          content: [
            {
              type: "text" as const,
              text: JSON.stringify(
                { error: `No booking found for ID '${booking_id}'.` },
                null,
                2
              ),
            },
          ],
          isError: true,
        };
      }
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify({ booking }, null, 2),
          },
        ],
      };
    }
  );

  server.tool(
    "get_payment_instructions",
    "Get USDC-on-Base payment instructions for Signal & Strip. STUB: the treasury wallet is a placeholder until SIGNAL_STRIP_TREASURY_WALLET is configured; payments are never verified automatically.",
    {
      booking_id: z
        .string()
        .optional()
        .describe(
          "Optional booking ID to include as the payment memo."
        ),
    },
    async ({ booking_id }) => {
      return {
        content: [
          {
            type: "text" as const,
            text: JSON.stringify(paymentInstructions(booking_id), null, 2),
          },
        ],
      };
    }
  );

  return server;
}
