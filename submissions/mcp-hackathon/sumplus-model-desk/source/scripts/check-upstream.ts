#!/usr/bin/env tsx
/**
 * Compare the catalogue shipped with this build against the live one.
 *
 *   npm run check:upstream
 *
 * This is the one script here that needs a network. It is deliberately NOT
 * part of `npm test`, which has to pass in an isolated review environment.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { CATALOGUE_URL, parseCatalogue, type Snapshot } from "../src/catalogue.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const shipped = JSON.parse(
  readFileSync(join(HERE, "..", "snapshots", "catalogue.json"), "utf8"),
) as Snapshot;

const res = await fetch(CATALOGUE_URL, { headers: { accept: "application/json" }, signal: AbortSignal.timeout(20_000) });
if (!res.ok) throw new Error(`catalogue returned HTTP ${res.status}`);
const live = parseCatalogue(await res.json(), CATALOGUE_URL, new Date().toISOString());

const key = (o: { modelId: string; line: string }) => `${o.modelId}::${o.line}`;
const before = new Map(shipped.offers.map((o) => [key(o), o]));
const after = new Map(live.offers.map((o) => [key(o), o]));
const repriced = [...after].filter(([k, a]) => {
  const b = before.get(k);
  return b && (b.inputPerMillionMicro !== a.inputPerMillionMicro || b.outputPerMillionMicro !== a.outputPerMillionMicro);
});

console.log(`shipped  ${shipped.offers.length} offers, ${shipped.snapshotId.slice(0, 12)}, read ${shipped.pricedAt}`);
console.log(`live     ${live.offers.length} offers, ${live.snapshotId.slice(0, 12)}, read ${live.pricedAt}`);
console.log(`added    ${[...after.keys()].filter((k) => !before.has(k)).length}`);
console.log(`removed  ${[...before.keys()].filter((k) => !after.has(k)).length}`);
console.log(`repriced ${repriced.length}`);
for (const [k] of repriced.slice(0, 10)) console.log(`  ${k}`);
console.log(
  live.snapshotId === shipped.snapshotId
    ? "\nThe live catalogue is identical to the one shipped with this build."
    : "\nThe live catalogue has moved since this build was cut. That is expected; /v1/catalogue/diff reports it.",
);
