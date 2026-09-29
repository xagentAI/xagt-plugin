#!/usr/bin/env tsx
/**
 * Read the catalogue once and write it to snapshots/catalogue.json.
 *
 * This is the copy shipped with the submission. Everything a reviewer checks
 * offline is recomputed from it, and /v1/catalogue/diff compares the live
 * catalogue against it, so the file is the fixed point of the whole evidence
 * story and is written deliberately rather than on every boot.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { CATALOGUE_URL, parseCatalogue } from "../src/catalogue.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "snapshots", "catalogue.json");

const res = await fetch(CATALOGUE_URL, {
  headers: { accept: "application/json" },
  signal: AbortSignal.timeout(20_000),
});
if (!res.ok) throw new Error(`catalogue returned HTTP ${res.status}`);

const snapshot = parseCatalogue(await res.json(), CATALOGUE_URL, new Date().toISOString());
mkdirSync(dirname(OUT), { recursive: true });
writeFileSync(OUT, `${JSON.stringify(snapshot, null, 2)}\n`);

const ids = new Set(snapshot.offers.map((o) => o.modelId));
const byId = new Map<string, number>();
for (const o of snapshot.offers) byId.set(o.modelId, (byId.get(o.modelId) ?? 0) + 1);
const multi = [...byId.values()].filter((n) => n > 1).length;

console.log(`wrote ${OUT}`);
console.log(`  offers        ${snapshot.offers.length}`);
console.log(`  unique ids    ${ids.size}`);
console.log(`  ids with more than one offer ${multi}`);
console.log(`  snapshotId    ${snapshot.snapshotId}`);
console.log(`  pricedAt      ${snapshot.pricedAt}`);
