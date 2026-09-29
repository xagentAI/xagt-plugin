import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The catalogue this desk prices against.
 *
 * One entry in the upstream catalogue is an OFFER: a model id served on a
 * particular line, at that line's price. The same id appears on several lines
 * at different prices, so an id on its own does not identify a price and
 * cannot be the unit anything is grouped by.
 */

export const CATALOGUE_URL =
  process.env.CATALOGUE_URL ?? "https://router.sumplus.xyz/v1/models";

/** How long a fetched catalogue is served before a refresh is attempted. */
export const REFRESH_SECONDS = Number(process.env.REFRESH_SECONDS ?? 300);

export type Offer = {
  /** The model id. Not unique in the catalogue: several lines carry the same id. */
  modelId: string;
  name: string;
  line: string;
  /** Empty string for 14 of the current entries. Empty is a value, not a gap. */
  lineCode: string;
  ownedBy: string;
  context: number;
  maxOutput: number;
  availability: string;
  /**
   * Prices in micro-dollars per million tokens, as integers. The upstream
   * figures are decimals like 0.435, and decimals in floating point do not
   * survive arithmetic intact, so they are widened to integers once here and
   * every later calculation stays in integers.
   */
  inputPerMillionMicro: number;
  outputPerMillionMicro: number;
  cacheHitPerMillionMicro: number | null;
  description: string;
};

export type Snapshot = {
  /** sha256 over the canonical offers. Two identical catalogues share an id. */
  snapshotId: string;
  /** When this catalogue was read from upstream. */
  pricedAt: string;
  source: string;
  offers: Offer[];
};

/** An offer's identity: the id alone is not one. */
export function offerKey(o: Pick<Offer, "modelId" | "line">): string {
  return `${o.modelId}::${o.line}`;
}

function toMicro(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  // Prices carry at most a few decimal places; rounding at this one point
  // turns them into exact integers before any multiplication happens.
  return Math.round(value * 1_000_000);
}

export function parseCatalogue(body: unknown, source: string, pricedAt: string): Snapshot {
  const rows = Array.isArray(body)
    ? body
    : Array.isArray((body as { data?: unknown[] })?.data)
      ? ((body as { data: unknown[] }).data as unknown[])
      : null;
  if (!rows) throw new Error("the catalogue response carried no list of models");

  const offers: Offer[] = [];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const r = row as Record<string, unknown>;
    const inputPerMillionMicro = toMicro(r.input_per_million);
    const outputPerMillionMicro = toMicro(r.output_per_million);
    if (
      typeof r.id !== "string" ||
      typeof r.line !== "string" ||
      inputPerMillionMicro === null ||
      outputPerMillionMicro === null ||
      typeof r.context !== "number" ||
      typeof r.max_output !== "number"
    ) {
      // An entry that cannot be priced is left out rather than defaulted to
      // zero: a missing price rendered as free is the worst possible answer.
      continue;
    }
    offers.push({
      modelId: r.id,
      name: typeof r.name === "string" ? r.name : r.id,
      line: r.line,
      lineCode: typeof r.line_code === "string" ? r.line_code : "",
      ownedBy: typeof r.owned_by === "string" ? r.owned_by : "",
      context: r.context,
      maxOutput: r.max_output,
      availability: typeof r.availability === "string" ? r.availability : "unknown",
      inputPerMillionMicro,
      outputPerMillionMicro,
      cacheHitPerMillionMicro: toMicro(r.cache_hit_per_million),
      description: typeof r.description === "string" ? r.description : "",
    });
  }

  if (offers.length === 0) throw new Error("the catalogue response carried no priceable offers");
  return { snapshotId: snapshotIdOf(offers), pricedAt, source, offers };
}

/**
 * Content address of a catalogue: the same offers in, the same id out.
 *
 * The canonical form is one JSON array per offer, fields in the order below,
 * sorted, newline separated. JSON quoting is what makes it unambiguous: a
 * separator character can be invisible in source and silently differ between
 * two implementations of this function, and then nobody can reproduce the id
 * from reading the code.
 */
export const DIGEST_FIELDS =
  "[modelId, line, lineCode, context, maxOutput, availability, inputPerMillionMicro, outputPerMillionMicro, cacheHitPerMillionMicro]";

export function canonicalForm(offers: Offer[]): string {
  return offers
    .map((o) =>
      JSON.stringify([
        o.modelId,
        o.line,
        o.lineCode,
        o.context,
        o.maxOutput,
        o.availability,
        o.inputPerMillionMicro,
        o.outputPerMillionMicro,
        o.cacheHitPerMillionMicro,
      ]),
    )
    .sort()
    .join("\n");
}

export function snapshotIdOf(offers: Offer[]): string {
  return createHash("sha256").update(canonicalForm(offers), "utf8").digest("hex");
}

export type CatalogueState = {
  snapshot: Snapshot | null;
  /** Seconds since the served catalogue was read from upstream. */
  staleSeconds: number | null;
  lastError: string | null;
  lastAttemptAt: string | null;
  /** How many refreshes have succeeded since this process started. */
  refreshCount: number;
  /** True while the answer still comes from the snapshot shipped in the image. */
  servingShippedSnapshot: boolean;
};

/**
 * The catalogue shipped inside the image, loaded at boot.
 *
 * A process that restarts while upstream happens to be unreachable would
 * otherwise answer "no catalogue" to whoever knocked first, which reads as a
 * dead service. It answers from this instead, reporting honestly how old it
 * is, and replaces it as soon as a refresh succeeds.
 */
function shippedSnapshot(): Snapshot | null {
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    return JSON.parse(readFileSync(join(here, "..", "snapshots", "catalogue.json"), "utf8")) as Snapshot;
  } catch {
    return null;
  }
}

let state: CatalogueState = {
  snapshot: shippedSnapshot(),
  staleSeconds: null,
  lastError: null,
  lastAttemptAt: null,
  refreshCount: 0,
  servingShippedSnapshot: true,
};

export function currentState(): CatalogueState {
  const snapshot = state.snapshot;
  return {
    ...state,
    staleSeconds: snapshot
      ? Math.floor((Date.now() - Date.parse(snapshot.pricedAt)) / 1000)
      : null,
  };
}

/** Serve the cached catalogue whatever happens; report how old it is. */
export async function ensureCatalogue(): Promise<CatalogueState> {
  const current = currentState();
  const fresh =
    current.snapshot !== null &&
    current.staleSeconds !== null &&
    current.staleSeconds < REFRESH_SECONDS;
  if (fresh) return current;

  try {
    const res = await fetch(CATALOGUE_URL, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(15_000),
    });
    if (!res.ok) throw new Error(`upstream returned HTTP ${res.status}`);
    const snapshot = parseCatalogue(await res.json(), CATALOGUE_URL, new Date().toISOString());
    state = {
      snapshot,
      staleSeconds: 0,
      lastError: null,
      lastAttemptAt: new Date().toISOString(),
      refreshCount: state.refreshCount + 1,
      servingShippedSnapshot: false,
    };
  } catch (err) {
    // A failed refresh does not discard what we already have. The age travels
    // with every answer so a caller can decide for itself.
    state = {
      ...state,
      lastError: err instanceof Error ? err.message : String(err),
      lastAttemptAt: new Date().toISOString(),
    };
  }
  return currentState();
}

/** Used by the tests and by the offline verifier, which never touch a network. */
export function loadSnapshot(snapshot: Snapshot): void {
  state = {
    snapshot,
    staleSeconds: 0,
    lastError: null,
    lastAttemptAt: new Date().toISOString(),
    refreshCount: state.refreshCount,
    servingShippedSnapshot: false,
  };
}
