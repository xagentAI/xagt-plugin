import { getVenue, listVenues, VENUES } from "./venues.js";

const WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

function pad(value) {
  return String(value).padStart(2, "0");
}

function ymd(year, month, day) {
  return `${year}-${pad(month)}-${pad(day)}`;
}

function nthWeekday(year, month, weekday, n) {
  const first = new Date(Date.UTC(year, month - 1, 1));
  const firstWeekday = first.getUTCDay();
  return 1 + ((weekday - firstWeekday + 7) % 7) + (n - 1) * 7;
}

function lastWeekday(year, month, weekday) {
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const lastWeekdayValue = new Date(Date.UTC(year, month - 1, last)).getUTCDay();
  return last - ((lastWeekdayValue - weekday + 7) % 7);
}

export function tzOffsetMin(tz, utcMs) {
  if (tz === "UTC") return 0;
  if (tz === "Asia/Tokyo") return 9 * 60;
  if (tz === "Asia/Hong_Kong") return 8 * 60;
  const year = new Date(utcMs).getUTCFullYear();
  if (tz === "America/New_York") {
    const start = Date.UTC(year, 2, nthWeekday(year, 3, 0, 2), 7, 0, 0);
    const end = Date.UTC(year, 10, nthWeekday(year, 11, 0, 1), 6, 0, 0);
    return utcMs >= start && utcMs < end ? -4 * 60 : -5 * 60;
  }
  if (tz === "Europe/London") {
    const start = Date.UTC(year, 2, lastWeekday(year, 3, 0), 1, 0, 0);
    const end = Date.UTC(year, 9, lastWeekday(year, 10, 0), 1, 0, 0);
    return utcMs >= start && utcMs < end ? 60 : 0;
  }
  throw new Error(`unsupported timezone: ${tz}`);
}

export function localParts(tz, utcMs) {
  const offsetMin = tzOffsetMin(tz, utcMs);
  const local = new Date(utcMs + offsetMin * 60 * 1000);
  const year = local.getUTCFullYear();
  const month = local.getUTCMonth() + 1;
  const day = local.getUTCDate();
  const hour = local.getUTCHours();
  const minute = local.getUTCMinutes();
  const second = local.getUTCSeconds();
  return {
    year,
    month,
    day,
    hour,
    minute,
    second,
    offsetMin,
    ymd: ymd(year, month, day),
    weekday: local.getUTCDay(),
    hhmm: `${pad(hour)}:${pad(minute)}`
  };
}

export function localToUtc(tz, year, month, day, hour, minute, second = 0) {
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  let offsetMin = tzOffsetMin(tz, asUtc);
  let utcMs = asUtc - offsetMin * 60 * 1000;
  offsetMin = tzOffsetMin(tz, utcMs);
  utcMs = asUtc - offsetMin * 60 * 1000;
  return utcMs;
}

function formatOffset(offsetMin) {
  const sign = offsetMin >= 0 ? "+" : "-";
  const absolute = Math.abs(offsetMin);
  return `${sign}${pad(Math.floor(absolute / 60))}:${pad(absolute % 60)}`;
}

export function formatInstant(tz, utcMs) {
  const parts = localParts(tz, utcMs);
  return `${ymd(parts.year, parts.month, parts.day)}T${pad(parts.hour)}:${pad(parts.minute)}:${pad(parts.second)}${formatOffset(parts.offsetMin)}`;
}

function parseHHmm(value) {
  if (value === "24:00") return { hour: 24, minute: 0 };
  const [hour, minute] = value.split(":").map(Number);
  return { hour, minute };
}

function minutesOfDay(hhmm) {
  const { hour, minute } = parseHHmm(hhmm);
  return hour * 60 + minute;
}

function addDays(year, month, day, delta) {
  const next = new Date(Date.UTC(year, month - 1, day + delta));
  return { year: next.getUTCFullYear(), month: next.getUTCMonth() + 1, day: next.getUTCDate() };
}

function sessionsForDate(venue, dateStr) {
  const holiday = venue.holidays[dateStr] ?? null;
  if (holiday?.type === "closed") {
    return { holiday, sessions: [] };
  }
  const sessions = venue.sessions.map((session) => ({ ...session }));
  if (holiday?.type === "early_close") {
    const regular = sessions.find((session) => session.id === "regular");
    if (regular) {
      regular.end = holiday.regularEnd;
      regular.earlyClose = true;
    }
    const post = sessions.find((session) => session.id === "post");
    if (post && regular) {
      post.start = holiday.regularEnd;
    }
    return { holiday, sessions: sessions.filter((session) => minutesOfDay(session.start) < minutesOfDay(session.end)) };
  }
  return { holiday, sessions };
}

function localDateFromYmd(dateStr) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) return null;
  return { year: Number(match[1]), month: Number(match[2]), day: Number(match[3]) };
}

export function daySchedule(venueId, dateStr) {
  const venue = getVenue(venueId);
  if (!venue) return { error: "unknown_venue", message: `Unknown venue: ${venueId}` };
  const parsed = localDateFromYmd(dateStr);
  if (!parsed) return { error: "invalid_date", message: "date must be YYYY-MM-DD in the venue timezone" };

  const weekday = new Date(Date.UTC(parsed.year, parsed.month - 1, parsed.day)).getUTCDay();
  const isWeekend = venue.weekend.includes(weekday);
  const { holiday, sessions } = isWeekend ? { holiday: null, sessions: [] } : sessionsForDate(venue, dateStr);

  const mapped = sessions.map((session) => {
    const start = parseHHmm(session.start);
    const end = parseHHmm(session.end);
    const endDate = end.hour === 24 ? addDays(parsed.year, parsed.month, parsed.day, 1) : parsed;
    const endHour = end.hour === 24 ? 0 : end.hour;
    const openUtc = localToUtc(venue.timezone, parsed.year, parsed.month, parsed.day, start.hour, start.minute);
    const closeUtc = localToUtc(venue.timezone, endDate.year, endDate.month, endDate.day, endHour, end.minute);
    return {
      id: session.id,
      label: session.label,
      open: formatInstant(venue.timezone, openUtc),
      close: formatInstant(venue.timezone, closeUtc),
      openUtc: new Date(openUtc).toISOString(),
      closeUtc: new Date(closeUtc).toISOString(),
      earlyClose: Boolean(session.earlyClose)
    };
  });

  let status = "open";
  if (isWeekend) status = "weekend";
  else if (holiday?.type === "closed") status = "holiday";
  else if (mapped.length === 0) status = "closed";

  return {
    venue: venue.id,
    mic: venue.mic,
    name: venue.name,
    date: dateStr,
    timezone: venue.timezone,
    weekday: WEEKDAYS[weekday],
    closed: mapped.length === 0,
    status,
    holiday: holiday ? { type: holiday.type, name: holiday.name } : null,
    sessions: mapped
  };
}

function nextOpenAfter(venue, fromUtc) {
  for (let offset = 0; offset <= 10; offset += 1) {
    const cursor = localParts(venue.timezone, fromUtc + offset * 24 * 60 * 60 * 1000);
    const schedule = daySchedule(venue.id, cursor.ymd);
    for (const session of schedule.sessions) {
      const openMs = Date.parse(session.openUtc);
      if (openMs > fromUtc) {
        return { at: session.open, atUtc: session.openUtc, session: session.id, date: schedule.date };
      }
    }
  }
  return null;
}

export function resolveSession(venueId, instant) {
  const venue = getVenue(venueId);
  if (!venue) return { error: "unknown_venue", message: `Unknown venue: ${venueId}` };
  const utcMs = instant instanceof Date ? instant.getTime() : Date.parse(instant);
  if (!Number.isFinite(utcMs)) return { error: "invalid_time", message: "at must be an ISO-8601 timestamp" };

  const local = localParts(venue.timezone, utcMs);
  const schedule = daySchedule(venue.id, local.ymd);
  const nowMinutes = local.hour * 60 + local.minute + local.second / 60;

  let current = null;
  for (const session of schedule.sessions) {
    const openMs = Date.parse(session.openUtc);
    const closeMs = Date.parse(session.closeUtc);
    if (utcMs >= openMs && utcMs < closeMs) {
      current = session;
      break;
    }
  }

  let phase = "closed";
  if (schedule.status === "weekend") phase = "weekend";
  else if (schedule.status === "holiday") phase = "holiday";
  else if (current) phase = current.id;

  const nextChange = current
    ? { type: "close", session: current.id, at: current.close, atUtc: current.closeUtc }
    : (() => {
        const upcoming = schedule.sessions.find((session) => Date.parse(session.openUtc) > utcMs);
        if (upcoming) return { type: "open", session: upcoming.id, at: upcoming.open, atUtc: upcoming.openUtc };
        const next = nextOpenAfter(venue, utcMs);
        return next ? { type: "open", session: next.session, at: next.at, atUtc: next.atUtc } : null;
      })();

  return {
    venue: venue.id,
    mic: venue.mic,
    name: venue.name,
    at: formatInstant(venue.timezone, utcMs),
    atUtc: new Date(utcMs).toISOString(),
    localDate: local.ymd,
    localTime: `${pad(local.hour)}:${pad(local.minute)}:${pad(local.second)}`,
    timezone: venue.timezone,
    utcOffset: formatOffset(local.offsetMin),
    phase,
    inSession: Boolean(current),
    session: current,
    nextChange,
    holiday: schedule.holiday,
    weekday: schedule.weekday,
    minutesOfLocalDay: Math.floor(nowMinutes)
  };
}

export function venueDescriptor(venueId) {
  const venue = getVenue(venueId);
  if (!venue) return null;
  const year = 2026;
  const holidays = Object.entries(venue.holidays)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([date, info]) => ({ date, ...info }));
  return {
    id: venue.id,
    mic: venue.mic,
    name: venue.name,
    timezone: venue.timezone,
    weekend: venue.weekend,
    sessions: venue.sessions,
    holidays,
    year,
    sources: venue.sources
  };
}

export { getVenue, listVenues, VENUES };
