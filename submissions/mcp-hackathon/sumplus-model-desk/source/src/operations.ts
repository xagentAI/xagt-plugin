import type { Offer, Snapshot } from "./catalogue.js";
import { plan, resolve as resolveModel, validateTokens, MAX_ROWS } from "./plan.js";
import { costOf, money, priceJob, usd } from "./pricing.js";

/**
 * The five operations, in one place.
 *
 * Both the REST routes and the JSON-RPC endpoint dispatch here. Two copies of
 * an operation drift, and the day they drift is the day a caller gets a
 * different answer depending on which door it came through.
 */

export type Operation = { status: number; body: unknown };

export type CatalogueQuery = {
  line?: string | null;
  minContext?: number;
  limit?: number;
};

function publicOffer(o: Offer) {
  return {
    modelId: o.modelId,
    name: o.name,
    line: o.line,
    lineCode: o.lineCode,
    ownedBy: o.ownedBy,
    context: o.context,
    maxOutput: o.maxOutput,
    availability: o.availability,
    inputPerMillion: usd(o.inputPerMillionMicro),
    outputPerMillion: usd(o.outputPerMillionMicro),
    cacheHitPerMillion: o.cacheHitPerMillionMicro === null ? null : usd(o.cacheHitPerMillionMicro),
  };
}

export function runPlanCall(snapshot: Snapshot, staleSeconds: number, args: unknown): Operation {
  const body = (args ?? {}) as Record<string, unknown>;
  const result = plan(snapshot, staleSeconds, body as never);
  if ("error" in result) {
    return { status: result.error === "unknown_model" ? 404 : 422, body: result };
  }
  return { status: 200, body: result };
}

export function runQuote(snapshot: Snapshot, staleSeconds: number, args: unknown): Operation {
  const body = (args ?? {}) as Record<string, unknown>;
  const inputTokens = body.inputTokens as number;
  const outputTokens = body.outputTokens as number;

  const invalid = validateTokens({ inputTokens, outputTokens });
  if (invalid) return { status: 422, body: invalid };

  const modelId = String(body.modelId ?? "");
  const line = body.line === undefined ? null : String(body.line);
  const candidates = snapshot.offers.filter(
    (o) => o.modelId === modelId && (line === null || o.line === line),
  );

  if (candidates.length === 0) {
    const known = resolveModel(snapshot, modelId);
    if ("error" in known) return { status: 404, body: known };
    return {
      status: 404,
      body: {
        error: "unknown_model",
        message: `The id ${modelId} is in this catalogue, but not on line ${line}.`,
        requested: { modelId, line },
        availableLines: known.offers.map((o) => o.line),
      },
    };
  }

  const cachedInputTokens = Number(body.cachedInputTokens ?? 0);
  const quotes = candidates
    .map((o) => {
      const job = priceJob(o, inputTokens, outputTokens);
      const cached =
        cachedInputTokens > 0 && o.cacheHitPerMillionMicro !== null
          ? money(costOf(cachedInputTokens, o.cacheHitPerMillionMicro))
          : null;
      return {
        modelId: o.modelId,
        line: o.line,
        lineCode: o.lineCode,
        inputCost: job.input,
        outputCost: job.output,
        cachedInputCost: cached,
        totalCost: money(job.total.microUsd + (cached?.microUsd ?? 0)),
        context: o.context,
        maxOutput: o.maxOutput,
        availability: o.availability,
        ...(o.inputPerMillionMicro === 0 && o.outputPerMillionMicro === 0
          ? { listedAtZero: true }
          : {}),
      };
    })
    .sort((a, b) => a.totalCost.microUsd - b.totalCost.microUsd);

  return {
    status: 200,
    body: {
      request: { modelId, line, inputTokens, outputTokens, cachedInputTokens },
      modelId,
      offerCount: quotes.length,
      quotes,
      snapshotId: snapshot.snapshotId,
      pricedAt: snapshot.pricedAt,
      staleSeconds,
    },
  };
}

export function runResolve(snapshot: Snapshot, staleSeconds: number, args: unknown): Operation {
  const body = (args ?? {}) as Record<string, unknown>;
  const modelId = String(body.modelId ?? "");
  const result = resolveModel(snapshot, modelId);
  return { status: "error" in result ? 404 : 200, body: { ...result, staleSeconds } };
}

export function runCatalogue(snapshot: Snapshot, staleSeconds: number, args: unknown): Operation {
  const q = (args ?? {}) as CatalogueQuery;
  const minContext = Number(q.minContext ?? 0);
  const rows = snapshot.offers
    .filter((o) => (q.line ? o.line === q.line : true))
    .filter((o) => o.context >= minContext)
    .slice(0, Math.min(Number(q.limit ?? MAX_ROWS), MAX_ROWS))
    .map(publicOffer);

  return {
    status: 200,
    body: {
      offers: rows,
      returned: rows.length,
      totalOffers: snapshot.offers.length,
      uniqueModelIds: new Set(snapshot.offers.map((o) => o.modelId)).size,
      snapshotId: snapshot.snapshotId,
      pricedAt: snapshot.pricedAt,
      staleSeconds,
    },
  };
}

/** What changed between the catalogue submitted with this build and today's. */
export function runCatalogueDiff(submitted: Snapshot, now: Snapshot): Operation {
  const key = (o: Offer) => `${o.modelId}::${o.line}`;
  const before = new Map(submitted.offers.map((o) => [key(o), o]));
  const after = new Map(now.offers.map((o) => [key(o), o]));

  const added = [...after.keys()].filter((k) => !before.has(k));
  const removed = [...before.keys()].filter((k) => !after.has(k));
  const repriced: unknown[] = [];
  const rewindowed: unknown[] = [];

  for (const [k, a] of after) {
    const b = before.get(k);
    if (!b) continue;
    if (
      a.inputPerMillionMicro !== b.inputPerMillionMicro ||
      a.outputPerMillionMicro !== b.outputPerMillionMicro
    ) {
      repriced.push({
        offer: k,
        inputPerMillion: { was: usd(b.inputPerMillionMicro), now: usd(a.inputPerMillionMicro) },
        outputPerMillion: { was: usd(b.outputPerMillionMicro), now: usd(a.outputPerMillionMicro) },
      });
    }
    if (a.context !== b.context || a.maxOutput !== b.maxOutput) {
      rewindowed.push({
        offer: k,
        context: { was: b.context, now: a.context },
        maxOutput: { was: b.maxOutput, now: a.maxOutput },
      });
    }
  }

  return {
    status: 200,
    body: {
      submittedSnapshotId: submitted.snapshotId,
      submittedPricedAt: submitted.pricedAt,
      currentSnapshotId: now.snapshotId,
      currentPricedAt: now.pricedAt,
      identical: now.snapshotId === submitted.snapshotId,
      counts: {
        submitted: submitted.offers.length,
        current: now.offers.length,
        added: added.length,
        removed: removed.length,
        repriced: repriced.length,
        rewindowed: rewindowed.length,
      },
      added,
      removed,
      repriced,
      rewindowed,
      // Said plainly, because the opposite claim would be false: two readings of
      // one source agreeing proves the source moved, not that it is correct.
      whatThisShows:
        "The upstream catalogue is live and changes over time. It does not independently confirm that any price is correct.",
    },
  };
}
