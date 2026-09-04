import { daySchedule, listVenues, resolveSession, venueDescriptor } from "./calendar.js";

export const SLUG = "kele0929-venueclock";

export function healthBody(commit) {
  return { status: "ok", commit };
}

export function proofBody(commit) {
  return { schemaVersion: 1, slug: SLUG, commit };
}

function json(status, body) {
  return { status, headers: { "content-type": "application/json; charset=utf-8" }, body };
}

function notFound(message) {
  return json(404, { error: "not_found", message });
}

function badRequest(error, message) {
  return json(400, { error, message });
}

export function route(url, { commit, now = () => new Date() } = {}) {
  const parsed = url instanceof URL ? url : new URL(url, "http://venueclock.local");
  let pathname = parsed.pathname;
  if (pathname.length > 1 && pathname.endsWith("/")) pathname = pathname.slice(0, -1);

  if (pathname === "/health" || pathname === "/health.json") {
    return json(200, healthBody(commit));
  }
  if (pathname === "/.well-known/xagent-verification.json") {
    return json(200, proofBody(commit));
  }
  if (pathname === "/v1" || pathname === "/v1/index.json") {
    return json(200, {
      name: "VenueClock",
      slug: SLUG,
      commit,
      endpoints: {
        health: "/health.json",
        proof: "/.well-known/xagent-verification.json",
        venues: "/v1/venues.json",
        venue: "/v1/venues/{id}.json",
        day: "/v1/resolve/{id}/{YYYY-MM-DD}.json",
        instant: "/v1/resolve?venue={id}&at={iso8601}"
      }
    });
  }
  if (pathname === "/v1/venues" || pathname === "/v1/venues.json") {
    return json(200, { venues: listVenues() });
  }

  const venueFile = /^\/v1\/venues\/([a-z0-9]+?)(?:\.json)?$/.exec(pathname);
  if (venueFile) {
    const descriptor = venueDescriptor(venueFile[1]);
    if (!descriptor) return notFound(`Unknown venue: ${venueFile[1]}`);
    return json(200, descriptor);
  }

  const dayFile = /^\/v1\/resolve\/([a-z0-9]+)\/(\d{4}-\d{2}-\d{2})(?:\.json)?$/.exec(pathname);
  if (dayFile) {
    const result = daySchedule(dayFile[1], dayFile[2]);
    if (result.error) return result.error === "unknown_venue" ? notFound(result.message) : badRequest(result.error, result.message);
    return json(200, result);
  }

  if (pathname === "/v1/resolve") {
    const venue = parsed.searchParams.get("venue");
    const date = parsed.searchParams.get("date");
    const at = parsed.searchParams.get("at");
    if (!venue) return badRequest("missing_venue", "query parameter venue is required");
    if (date && !at) {
      const result = daySchedule(venue, date);
      if (result.error) return result.error === "unknown_venue" ? notFound(result.message) : badRequest(result.error, result.message);
      return json(200, result);
    }
    const result = resolveSession(venue, at || now());
    if (result.error) {
      if (result.error === "unknown_venue") return notFound(result.message);
      return badRequest(result.error, result.message);
    }
    return json(200, result);
  }

  if (pathname === "/mcp/tools.json") {
    return json(200, {
      protocol: "mcp",
      tools: [
        {
          name: "list_venues",
          description: "List supported market venues (MIC, timezone).",
          inputSchema: { type: "object", properties: {}, additionalProperties: false }
        },
        {
          name: "get_venue",
          description: "Return session rules, timezone, and 2026 holidays for a venue.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            required: ["venue"],
            properties: { venue: { type: "string", description: "Venue id or MIC, e.g. xnys or XNYS" } }
          }
        },
        {
          name: "resolve_session",
          description: "Return whether a venue is in pre-market, regular, after-hours, holiday, or weekend at an instant, plus the next open or close.",
          inputSchema: {
            type: "object",
            additionalProperties: false,
            required: ["venue"],
            properties: {
              venue: { type: "string" },
              at: { type: "string", description: "ISO-8601 timestamp. Defaults to now on the live HTTP server." },
              date: { type: "string", description: "YYYY-MM-DD in the venue timezone. Returns the full day schedule instead of an instant." }
            }
          }
        }
      ]
    });
  }

  return notFound(`No route for ${pathname}`);
}

export function send(res, result) {
  const payload = `${JSON.stringify(result.body)}\n`;
  res.writeHead(result.status, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "public, max-age=60",
    "access-control-allow-origin": "*",
    "x-source-commit": result.body.commit ?? "",
    "content-length": Buffer.byteLength(payload)
  });
  res.end(payload);
}
