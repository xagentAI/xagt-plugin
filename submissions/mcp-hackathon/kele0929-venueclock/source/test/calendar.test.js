import assert from "node:assert/strict";
import test from "node:test";
import { daySchedule, resolveSession, tzOffsetMin } from "../src/calendar.js";
import { route } from "../src/http.js";

const COMMIT = "0123456789abcdef0123456789abcdef01234567";

test("US Eastern DST around 2026-03-08 and 2026-11-01", () => {
  const before = Date.parse("2026-03-08T06:59:00Z");
  const after = Date.parse("2026-03-08T07:00:00Z");
  assert.equal(tzOffsetMin("America/New_York", before), -5 * 60);
  assert.equal(tzOffsetMin("America/New_York", after), -4 * 60);
  const fallBefore = Date.parse("2026-11-01T05:59:00Z");
  const fallAfter = Date.parse("2026-11-01T06:00:00Z");
  assert.equal(tzOffsetMin("America/New_York", fallBefore), -4 * 60);
  assert.equal(tzOffsetMin("America/New_York", fallAfter), -5 * 60);
});

test("NYSE closed New Year's Day 2026", () => {
  const day = daySchedule("xnys", "2026-01-01");
  assert.equal(day.status, "holiday");
  assert.equal(day.sessions.length, 0);
  const resolved = resolveSession("XNYS", "2026-01-01T15:00:00Z");
  assert.equal(resolved.phase, "holiday");
});

test("NYSE Friday 2026-09-04 sessions", () => {
  const day = daySchedule("xnys", "2026-09-04");
  assert.equal(day.closed, false);
  assert.equal(day.weekday, "Friday");
  assert.equal(day.sessions.map((s) => s.id).join(","), "pre,regular,post");
  assert.equal(resolveSession("xnys", "2026-09-04T13:00:00Z").phase, "pre");
  assert.equal(resolveSession("xnys", "2026-09-04T15:00:00Z").phase, "regular");
  assert.equal(resolveSession("xnys", "2026-09-04T20:30:00Z").phase, "post");
  assert.equal(resolveSession("xnys", "2026-09-05T01:00:00Z").phase, "closed");
});

test("NYSE Labor Day 2026-09-07 is a holiday", () => {
  const day = daySchedule("xnys", "2026-09-07");
  assert.equal(day.status, "holiday");
  assert.equal(day.holiday.name, "Labor Day");
});

test("NYSE weekend", () => {
  const saturday = daySchedule("xnys", "2026-09-05");
  assert.equal(saturday.status, "weekend");
  assert.equal(resolveSession("xnys", "2026-09-05T15:00:00Z").phase, "weekend");
});

test("NYSE early close 2026-11-27", () => {
  const day = daySchedule("xnas", "2026-11-27");
  assert.equal(day.holiday.type, "early_close");
  const regular = day.sessions.find((s) => s.id === "regular");
  assert.match(regular.close, /13:00:00-05:00/);
  assert.equal(resolveSession("xnas", "2026-11-27T16:00:00Z").phase, "regular");
  assert.equal(resolveSession("xnas", "2026-11-27T18:30:00Z").phase, "post");
});

test("LSE regular session in BST", () => {
  const resolved = resolveSession("xlon", "2026-09-04T09:00:00Z");
  assert.equal(resolved.phase, "regular");
  assert.equal(resolved.utcOffset, "+01:00");
});

test("crypto is always regular", () => {
  assert.equal(resolveSession("crypto", "2026-09-05T03:00:00Z").phase, "regular");
  assert.equal(daySchedule("crypto", "2026-12-25").closed, false);
});

test("unknown venue and bad date", () => {
  assert.equal(daySchedule("xyz", "2026-09-04").error, "unknown_venue");
  assert.equal(daySchedule("xnys", "09/04/2026").error, "invalid_date");
  assert.equal(resolveSession("xnys", "not-a-time").error, "invalid_time");
});

test("HTTP health and proof bind the commit", () => {
  const health = route("/health.json", { commit: COMMIT });
  assert.equal(health.status, 200);
  assert.deepEqual(health.body, { status: "ok", commit: COMMIT });
  const proof = route("/.well-known/xagent-verification.json", { commit: COMMIT });
  assert.equal(proof.body.schemaVersion, 1);
  assert.equal(proof.body.slug, "kele0929-venueclock");
  assert.equal(proof.body.commit, COMMIT);
});

test("HTTP capability routes", () => {
  const venues = route("/v1/venues.json", { commit: COMMIT });
  assert.equal(venues.status, 200);
  assert.ok(venues.body.venues.some((v) => v.id === "xnys"));
  const day = route("/v1/resolve/xnys/2026-09-04.json", { commit: COMMIT });
  assert.equal(day.status, 200);
  assert.equal(day.body.weekday, "Friday");
  const instant = route("/v1/resolve?venue=XNYS&at=2026-09-04T15:00:00Z", { commit: COMMIT });
  assert.equal(instant.body.phase, "regular");
  const missing = route("/v1/resolve/nope/2026-09-04.json", { commit: COMMIT });
  assert.equal(missing.status, 404);
});
