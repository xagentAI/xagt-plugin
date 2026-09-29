import type { Offer, Snapshot } from "./catalogue.js";
import { money, priceJob, savingOf, usd, type Money } from "./pricing.js";

/**
 * Planning one call.
 *
 * The question a caller actually has is not "what does this model cost" but
 * "which offers can take this job, and what does each one charge for it".
 * Those are different questions because the same model id is sold on several
 * lines at different prices, and because an offer whose context or output
 * ceiling is too small does not fail loudly: it truncates, and the caller pays
 * for the truncated answer.
 */

export const MAX_TOKENS = 2_000_000;
export const MAX_ROWS = 50;

export type PlanRequest = {
  inputTokens: number;
  outputTokens: number;
  minContext?: number;
  minMaxOutput?: number;
  requireLines?: string[];
  excludeLines?: string[];
  baselineModelId?: string;
  /** Preview offers are left out unless this is set. */
  includePreview?: boolean;
  limit?: number;
};

export type EligibleOffer = {
  modelId: string;
  name: string;
  line: string;
  lineCode: string;
  inputCost: Money;
  outputCost: Money;
  totalCost: Money;
  context: number;
  maxOutput: number;
  availability: string;
  /**
   * The catalogue lists this offer at zero. That is what it says; it is not a
   * claim that the call is free, because a price of zero and a price nobody
   * has filled in look identical in this field.
   */
  listedAtZero?: boolean;
};

export type RejectedOffer = {
  modelId: string;
  line: string;
  lineCode: string;
  reason: string;
  /** Which single requirement ruled it out. */
  bindingConstraint:
    | "context"
    | "max_output"
    | "min_context"
    | "min_max_output"
    | "line"
    | "availability"
    | "not_token_priced";
  requiredValue: number | string;
  actualValue: number | string;
};

export type PlanError = {
  error: string;
  message: string;
  [key: string]: unknown;
};

export type PlanResult = {
  /** The job this answer priced, echoed so the answer stands on its own. */
  request: {
    inputTokens: number;
    outputTokens: number;
    minContext?: number;
    minMaxOutput?: number;
    requireLines?: string[];
    excludeLines?: string[];
    baselineModelId?: string;
    includePreview?: boolean;
    limit?: number;
  };
  eligible: EligibleOffer[];
  rejected: RejectedOffer[];
  eligibleCount: number;
  rejectedCount: number;
  /** True when rows were cut by `limit`. The count above is the real total. */
  truncated: boolean;
  omittedCount: number;
  savingsVsBaseline?: {
    baselineModelId: string;
    baselineOffer: { line: string; totalCost: Money } | null;
    baselineIneligible?: RejectedOffer[];
    cheapestOffer: { modelId: string; line: string; totalCost: Money };
    absolute: Money;
    ratio: string;
  };
  snapshotId: string;
  pricedAt: string;
  staleSeconds: number;
};

function nearestIds(snapshot: Snapshot, wanted: string): string[] {
  const ids = [...new Set(snapshot.offers.map((o) => o.modelId))];
  const target = wanted.toLowerCase();
  return ids
    .map((id) => {
      const lower = id.toLowerCase();
      let shared = 0;
      while (shared < lower.length && shared < target.length && lower[shared] === target[shared]) {
        shared += 1;
      }
      return { id, shared, contains: lower.includes(target) || target.includes(lower) };
    })
    .filter((c) => c.shared > 2 || c.contains)
    .sort((a, b) => b.shared - a.shared)
    .slice(0, 5)
    .map((c) => c.id);
}

export function validateTokens(req: PlanRequest): PlanError | null {
  for (const [field, value] of [
    ["inputTokens", req.inputTokens],
    ["outputTokens", req.outputTokens],
  ] as const) {
    if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
      return {
        error: "invalid_token_counts",
        message: `${field} must be a whole number of tokens, zero or more.`,
        field,
        received: value ?? null,
      };
    }
    if (value > MAX_TOKENS) {
      return {
        error: "invalid_token_counts",
        message: `${field} is ${value}, above the ceiling of ${MAX_TOKENS} this desk will price.`,
        field,
        received: value,
        maximum: MAX_TOKENS,
      };
    }
  }
  return null;
}

/**
 * The job has to fit inside the context window along with its own output, and
 * the output has to fit under the offer's output ceiling. Both are reported by
 * name when they bind, because "no" without a number is not an answer anyone
 * can act on.
 */
function judge(offer: Offer, req: PlanRequest): RejectedOffer | null {
  const needed = req.inputTokens + req.outputTokens;

  // Video and image models sit in the same catalogue with a context window and
  // an output ceiling of zero: they are not sold by the token at all, so their
  // per-million fields carry no meaning and their zero is not a price. A job
  // measured in tokens cannot be placed on one, and saying so by name is
  // better than dropping them silently.
  if (offer.context === 0 || offer.maxOutput === 0) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason:
        "This offer is not sold by the token: the catalogue gives it no context window or output ceiling, so its per-million figures do not price this job.",
      bindingConstraint: "not_token_priced",
      requiredValue: "priced per token",
      actualValue: `context ${offer.context}, maxOutput ${offer.maxOutput}`,
    };
  }

  // Preview offers are real and priced, but a caller should choose one on
  // purpose rather than find it at the top of a list sorted by price.
  if (offer.availability !== "live" && req.includePreview !== true) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `This offer is marked ${offer.availability}, not live. Set includePreview to consider it.`,
      bindingConstraint: "availability",
      requiredValue: "live",
      actualValue: offer.availability,
    };
  }

  if (req.requireLines?.length && !req.requireLines.includes(offer.line)) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `Served on line ${offer.line}, which is not among the lines this request asked for.`,
      bindingConstraint: "line",
      requiredValue: req.requireLines.join(", "),
      actualValue: offer.line,
    };
  }
  if (req.excludeLines?.length && req.excludeLines.includes(offer.line)) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `Served on line ${offer.line}, which this request excluded.`,
      bindingConstraint: "line",
      requiredValue: `not ${req.excludeLines.join(", ")}`,
      actualValue: offer.line,
    };
  }
  if (offer.context < needed) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `Its context window holds ${offer.context} tokens, and this job needs ${needed} for the prompt plus its answer.`,
      bindingConstraint: "context",
      requiredValue: needed,
      actualValue: offer.context,
    };
  }
  if (offer.maxOutput < req.outputTokens) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `It will return at most ${offer.maxOutput} tokens, and this job asks for ${req.outputTokens}. The answer would be cut off and still billed.`,
      bindingConstraint: "max_output",
      requiredValue: req.outputTokens,
      actualValue: offer.maxOutput,
    };
  }
  if (req.minContext !== undefined && offer.context < req.minContext) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `Its context window is ${offer.context} tokens, below the ${req.minContext} this request asked for.`,
      bindingConstraint: "min_context",
      requiredValue: req.minContext,
      actualValue: offer.context,
    };
  }
  if (req.minMaxOutput !== undefined && offer.maxOutput < req.minMaxOutput) {
    return {
      modelId: offer.modelId,
      line: offer.line,
      lineCode: offer.lineCode,
      reason: `Its output ceiling is ${offer.maxOutput} tokens, below the ${req.minMaxOutput} this request asked for.`,
      bindingConstraint: "min_max_output",
      requiredValue: req.minMaxOutput,
      actualValue: offer.maxOutput,
    };
  }
  return null;
}

/** What to relax, and to what, so that the request has an answer at all. */
function relaxation(rejected: RejectedOffer[], offers: Offer[]): Record<string, unknown> {
  const bestContext = Math.max(...offers.map((o) => o.context));
  const bestMaxOutput = Math.max(...offers.map((o) => o.maxOutput));
  const binding = new Map<string, number>();
  for (const r of rejected) binding.set(r.bindingConstraint, (binding.get(r.bindingConstraint) ?? 0) + 1);

  return {
    largestContextAvailable: bestContext,
    largestMaxOutputAvailable: bestMaxOutput,
    bindingConstraintCounts: Object.fromEntries(binding),
    howToGetAnAnswer: [
      `Keep inputTokens + outputTokens at or under ${bestContext}.`,
      `Keep outputTokens at or under ${bestMaxOutput}.`,
    ],
  };
}

export function plan(
  snapshot: Snapshot,
  staleSeconds: number,
  req: PlanRequest,
): PlanResult | PlanError {
  const invalid = validateTokens(req);
  if (invalid) return invalid;

  if (req.baselineModelId) {
    const known = snapshot.offers.some((o) => o.modelId === req.baselineModelId);
    if (!known) {
      return {
        error: "unknown_model",
        message: `No offer in this catalogue carries the id ${req.baselineModelId}.`,
        requested: req.baselineModelId,
        // Both spellings, so a caller looking for either finds it.
        nearest: nearestIds(snapshot, req.baselineModelId),
        closestIds: nearestIds(snapshot, req.baselineModelId),
      };
    }
  }

  const eligible: EligibleOffer[] = [];
  const rejected: RejectedOffer[] = [];

  for (const offer of snapshot.offers) {
    const verdict = judge(offer, req);
    if (verdict) {
      rejected.push(verdict);
      continue;
    }
    const cost = priceJob(offer, req.inputTokens, req.outputTokens);
    eligible.push({
      modelId: offer.modelId,
      name: offer.name,
      line: offer.line,
      lineCode: offer.lineCode,
      inputCost: cost.input,
      outputCost: cost.output,
      totalCost: cost.total,
      context: offer.context,
      maxOutput: offer.maxOutput,
      availability: offer.availability,
      ...(offer.inputPerMillionMicro === 0 && offer.outputPerMillionMicro === 0
        ? { listedAtZero: true }
        : {}),
    });
  }

  if (eligible.length === 0) {
    return {
      error: "no_offer_meets_requirements",
      message: `None of the ${snapshot.offers.length} offers in this catalogue can take this job.`,
      request: { inputTokens: req.inputTokens, outputTokens: req.outputTokens },
      rejected: rejected.slice(0, MAX_ROWS),
      rejectedCount: rejected.length,
      ...relaxation(rejected, snapshot.offers),
      snapshotId: snapshot.snapshotId,
      pricedAt: snapshot.pricedAt,
      staleSeconds,
    };
  }

  eligible.sort((a, b) =>
    a.totalCost.microUsd === b.totalCost.microUsd
      ? a.modelId.localeCompare(b.modelId) || a.line.localeCompare(b.line)
      : a.totalCost.microUsd - b.totalCost.microUsd,
  );

  const limit = Math.min(req.limit ?? MAX_ROWS, MAX_ROWS);
  const result: PlanResult = {
    request: {
      inputTokens: req.inputTokens,
      outputTokens: req.outputTokens,
      ...(req.minContext !== undefined ? { minContext: req.minContext } : {}),
      ...(req.minMaxOutput !== undefined ? { minMaxOutput: req.minMaxOutput } : {}),
      ...(req.requireLines ? { requireLines: req.requireLines } : {}),
      ...(req.excludeLines ? { excludeLines: req.excludeLines } : {}),
      ...(req.baselineModelId ? { baselineModelId: req.baselineModelId } : {}),
      ...(req.includePreview !== undefined ? { includePreview: req.includePreview } : {}),
      ...(req.limit !== undefined ? { limit: req.limit } : {}),
    },
    eligible: eligible.slice(0, limit),
    rejected: rejected.slice(0, MAX_ROWS),
    eligibleCount: eligible.length,
    rejectedCount: rejected.length,
    // Rows are cut by price, so a dearer offer of an id that also has a cheap
    // one can fall off the end. Say so, rather than letting a caller read a
    // short list as the whole answer.
    truncated: eligible.length > limit,
    omittedCount: Math.max(0, eligible.length - limit),
    snapshotId: snapshot.snapshotId,
    pricedAt: snapshot.pricedAt,
    staleSeconds,
  };

  if (req.baselineModelId) {
    const cheapest = eligible[0];
    const baselineOffers = eligible.filter((o) => o.modelId === req.baselineModelId);
    if (baselineOffers.length === 0) {
      // The id the caller had in mind cannot take this job at all. That is the
      // answer, not an error: it is the case this desk exists to catch.
      result.savingsVsBaseline = {
        baselineModelId: req.baselineModelId,
        baselineOffer: null,
        baselineIneligible: rejected.filter((r) => r.modelId === req.baselineModelId),
        cheapestOffer: {
          modelId: cheapest.modelId,
          line: cheapest.line,
          totalCost: cheapest.totalCost,
        },
        absolute: money(0),
        ratio: "n/a",
      };
    } else {
      const baseline = baselineOffers.reduce((a, b) =>
        a.totalCost.microUsd <= b.totalCost.microUsd ? a : b,
      );
      const absolute = savingOf(baseline.totalCost.microUsd, cheapest.totalCost.microUsd);
      result.savingsVsBaseline = {
        baselineModelId: req.baselineModelId,
        baselineOffer: { line: baseline.line, totalCost: baseline.totalCost },
        cheapestOffer: {
          modelId: cheapest.modelId,
          line: cheapest.line,
          totalCost: cheapest.totalCost,
        },
        absolute: money(absolute),
        ratio:
          cheapest.totalCost.microUsd === 0
            ? "n/a"
            : `${Math.floor((baseline.totalCost.microUsd / cheapest.totalCost.microUsd) * 100) / 100}x`,
      };
    }
  }

  return result;
}

/** Every offer carrying one id, so a caller can see that an id is not a price. */
export function resolve(snapshot: Snapshot, modelId: string) {
  const offers = snapshot.offers.filter((o) => o.modelId === modelId);
  if (offers.length === 0) {
    return {
      error: "unknown_model",
      message: `No offer in this catalogue carries the id ${modelId}.`,
      requested: modelId,
      nearest: nearestIds(snapshot, modelId),
      closestIds: nearestIds(snapshot, modelId),
    } satisfies PlanError;
  }
  const sorted = [...offers].sort((a, b) => a.inputPerMillionMicro - b.inputPerMillionMicro);
  const cheapest = sorted[0];
  const dearest = sorted[sorted.length - 1];
  return {
    modelId,
    offerCount: offers.length,
    offers: sorted.map((o) => ({
      line: o.line,
      lineCode: o.lineCode,
      inputPerMillion: usd(o.inputPerMillionMicro),
      outputPerMillion: usd(o.outputPerMillionMicro),
      context: o.context,
      maxOutput: o.maxOutput,
      availability: o.availability,
    })),
    spread:
      cheapest.inputPerMillionMicro > 0
        ? `${Math.floor((dearest.inputPerMillionMicro / cheapest.inputPerMillionMicro) * 100) / 100}x`
        : "n/a",
    snapshotId: snapshot.snapshotId,
    pricedAt: snapshot.pricedAt,
  };
}
