/**
 * Venue session rules for 2026.
 *
 * US equity holidays / early closes: Nasdaq 2026 holiday calendar
 * (https://www.nasdaqtrader.com/trader.aspx?id=Calendar) and NYSE Group
 * 2025–2027 holiday schedule as reported by the exchanges.
 *
 * LSE dates follow UK bank holidays for 2026 (GOV.UK). Hours are the
 * London Stock Exchange electronic order book: 08:00–16:30 Europe/London.
 *
 * CRYPTO is a synthetic 24/7 venue (UTC). It is not an ISO MIC.
 */

const US_EQUITY_HOLIDAYS_2026 = {
  "2026-01-01": { type: "closed", name: "New Year's Day" },
  "2026-01-19": { type: "closed", name: "Martin Luther King, Jr. Day" },
  "2026-02-16": { type: "closed", name: "Washington's Birthday (Presidents' Day)" },
  "2026-04-03": { type: "closed", name: "Good Friday" },
  "2026-05-25": { type: "closed", name: "Memorial Day" },
  "2026-06-19": { type: "closed", name: "Juneteenth National Independence Day" },
  "2026-07-03": { type: "closed", name: "Independence Day (observed)" },
  "2026-09-07": { type: "closed", name: "Labor Day" },
  "2026-11-26": { type: "closed", name: "Thanksgiving Day" },
  "2026-11-27": { type: "early_close", name: "Day after Thanksgiving", regularEnd: "13:00" },
  "2026-12-24": { type: "early_close", name: "Christmas Eve", regularEnd: "13:00" },
  "2026-12-25": { type: "closed", name: "Christmas Day" }
};

const LSE_HOLIDAYS_2026 = {
  "2026-01-01": { type: "closed", name: "New Year's Day" },
  "2026-04-03": { type: "closed", name: "Good Friday" },
  "2026-04-06": { type: "closed", name: "Easter Monday" },
  "2026-05-04": { type: "closed", name: "Early May bank holiday" },
  "2026-05-25": { type: "closed", name: "Spring bank holiday" },
  "2026-08-31": { type: "closed", name: "Summer bank holiday" },
  "2026-12-25": { type: "closed", name: "Christmas Day" },
  "2026-12-28": { type: "closed", name: "Boxing Day (substitute)" }
};

export const VENUES = {
  xnys: {
    id: "xnys",
    mic: "XNYS",
    name: "New York Stock Exchange",
    timezone: "America/New_York",
    weekend: [0, 6],
    sessions: [
      { id: "pre", label: "pre-market", start: "04:00", end: "09:30" },
      { id: "regular", label: "regular", start: "09:30", end: "16:00" },
      { id: "post", label: "after-hours", start: "16:00", end: "20:00" }
    ],
    holidays: US_EQUITY_HOLIDAYS_2026,
    sources: [
      "https://www.nasdaqtrader.com/trader.aspx?id=Calendar",
      "https://www.nyse.com/"
    ]
  },
  xnas: {
    id: "xnas",
    mic: "XNAS",
    name: "Nasdaq Stock Market",
    timezone: "America/New_York",
    weekend: [0, 6],
    sessions: [
      { id: "pre", label: "pre-market", start: "04:00", end: "09:30" },
      { id: "regular", label: "regular", start: "09:30", end: "16:00" },
      { id: "post", label: "after-hours", start: "16:00", end: "20:00" }
    ],
    holidays: US_EQUITY_HOLIDAYS_2026,
    sources: ["https://www.nasdaqtrader.com/trader.aspx?id=Calendar"]
  },
  xlon: {
    id: "xlon",
    mic: "XLON",
    name: "London Stock Exchange",
    timezone: "Europe/London",
    weekend: [0, 6],
    sessions: [{ id: "regular", label: "regular", start: "08:00", end: "16:30" }],
    holidays: LSE_HOLIDAYS_2026,
    sources: ["https://www.gov.uk/bank-holidays"]
  },
  crypto: {
    id: "crypto",
    mic: null,
    name: "24/7 crypto (synthetic UTC venue)",
    timezone: "UTC",
    weekend: [],
    sessions: [{ id: "regular", label: "continuous", start: "00:00", end: "24:00" }],
    holidays: {},
    sources: []
  }
};

export function listVenues() {
  return Object.values(VENUES).map((venue) => ({
    id: venue.id,
    mic: venue.mic,
    name: venue.name,
    timezone: venue.timezone
  }));
}

export function getVenue(raw) {
  if (typeof raw !== "string" || !raw.trim()) return null;
  const key = raw.trim().toLowerCase();
  if (VENUES[key]) return VENUES[key];
  return Object.values(VENUES).find((venue) => venue.mic && venue.mic.toLowerCase() === key) ?? null;
}
