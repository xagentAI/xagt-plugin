/**
 * Booking-intent store.
 *
 * STUB STATUS: This is a LOCAL JSON FILE, not a real booking system.
 * - Booking intents are appended to data/bookings.json on this machine.
 * - There is no payment capture, no payment verification, no confirmation
 *   workflow, and no protection against double-booking.
 * - A booking created here is an INTENT ONLY. A human from Signal & Strip
 *   must manually confirm it after receiving payment off-band.
 * Replace with a real database + payment verification before public use.
 */

import { randomUUID } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export type BookingStatus = "pending_payment" | "confirmed" | "cancelled";

export interface BookingIntent {
  booking_id: string;
  package_id: string;
  package_name: string;
  price_usdc: number;
  buyer_handle: string;
  buyer_contact?: string;
  notes?: string;
  status: BookingStatus;
  created_at: string;
  /** Always true in this scaffold — nothing here captures payment. */
  intent_only: true;
}

const DATA_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "data"
);
const BOOKINGS_FILE = join(DATA_DIR, "bookings.json");

function loadAll(): BookingIntent[] {
  try {
    if (!existsSync(BOOKINGS_FILE)) return [];
    const raw = readFileSync(BOOKINGS_FILE, "utf-8");
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as BookingIntent[]) : [];
  } catch {
    // Corrupt file should not crash the server; start fresh in memory.
    return [];
  }
}

function saveAll(bookings: BookingIntent[]): void {
  mkdirSync(DATA_DIR, { recursive: true });
  writeFileSync(BOOKINGS_FILE, JSON.stringify(bookings, null, 2), "utf-8");
}

export function createBookingIntent(input: {
  package_id: string;
  package_name: string;
  price_usdc: number;
  buyer_handle: string;
  buyer_contact?: string;
  notes?: string;
}): BookingIntent {
  const bookings = loadAll();
  const intent: BookingIntent = {
    booking_id: `ss-${randomUUID().slice(0, 8)}`,
    package_id: input.package_id,
    package_name: input.package_name,
    price_usdc: input.price_usdc,
    buyer_handle: input.buyer_handle,
    buyer_contact: input.buyer_contact,
    notes: input.notes,
    status: "pending_payment",
    created_at: new Date().toISOString(),
    intent_only: true,
  };
  bookings.push(intent);
  saveAll(bookings);
  return intent;
}

export function getBooking(booking_id: string): BookingIntent | undefined {
  return loadAll().find((b) => b.booking_id === booking_id);
}
