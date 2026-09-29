/**
 * Captures the live registry into snapshots/registry.json.
 *
 * The snapshot is a test fixture and a provenance record, not a fallback: the
 * service always reads live. Pinning it here means the tests assert against a
 * registry state a reviewer can diff, instead of against whatever upstream
 * happens to say the day they run them.
 */
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { fetchResources } from "../src/registry.js";

const here = dirname(fileURLToPath(import.meta.url));
const snap = await fetchResources();
const out = join(here, "..", "snapshots", "registry.json");
writeFileSync(out, `${JSON.stringify(snap, null, 2)}\n`);
process.stdout.write(`wrote ${snap.resources.length} entries, digest ${snap.digest.slice(0, 16)}…\n`);
