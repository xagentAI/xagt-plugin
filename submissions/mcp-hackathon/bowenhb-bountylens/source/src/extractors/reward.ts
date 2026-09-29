import type { NormalizedIssueContext } from "../github/normalize.js";
import { clampConfidence, type EvidenceSignal } from "./types.js";

export type RewardSource = "body" | "comment" | "label" | "title";

export type RewardEvidence = {
  amount: number | null;
  currency: "USD" | null;
  source: RewardSource | null;
  sourceCount: number;
};

type RewardCandidate = {
  amount: number;
  source: RewardSource;
  snippet: string;
};

const rewardContextPattern = /(?:\/bounty|\bbount(?:y|ies)\b|\breward(?:ed|s)?\b|\bprize\b|\bpaid\b|\bpayment\b)/i;
const amountPattern = /\$\s*(\d[\d,]*(?:\.\d{1,2})?)(?:\s*USD)?|\b(\d[\d,]*(?:\.\d{1,2})?)\s*USD\b/gi;

function parseAmounts(text: string): number[] {
  const amounts: number[] = [];

  for (const match of text.matchAll(amountPattern)) {
    const rawAmount = match[1] ?? match[2];
    if (rawAmount === undefined) {
      continue;
    }

    const amount = Number(rawAmount.replaceAll(",", ""));
    if (Number.isFinite(amount) && amount > 0) {
      amounts.push(amount);
    }
  }

  return amounts;
}

function excerpt(text: string): string {
  return text.replace(/\s+/g, " ").trim().slice(0, 180);
}

function candidatesFromText(text: string, source: RewardSource): RewardCandidate[] {
  const candidates: RewardCandidate[] = [];

  for (const line of text.slice(0, 100_000).split(/\r?\n/)) {
    if (!rewardContextPattern.test(line)) {
      continue;
    }

    for (const amount of parseAmounts(line)) {
      candidates.push({ amount, source, snippet: excerpt(line) });
    }
  }

  return candidates;
}

/** Extract explicit USD reward evidence without guessing from unrelated numbers. */
export function extractReward(
  context: Pick<NormalizedIssueContext, "comments" | "issue">,
): EvidenceSignal<RewardEvidence> {
  const candidates: RewardCandidate[] = [
    ...candidatesFromText(context.issue.title, "title"),
    ...candidatesFromText(context.issue.body, "body"),
  ];

  const labelText = context.issue.labels.join(" ");
  if (rewardContextPattern.test(labelText)) {
    for (const amount of parseAmounts(labelText)) {
      candidates.push({ amount, source: "label", snippet: excerpt(labelText) });
    }
  }

  for (const comment of context.comments) {
    candidates.push(...candidatesFromText(comment.body, "comment"));
  }

  const selected = candidates[0];
  if (selected === undefined) {
    return {
      value: { amount: null, currency: null, source: null, sourceCount: 0 },
      confidence: 0.9,
      evidence: ["No explicit USD bounty or reward amount was found."],
    };
  }

  const confidenceBySource: Record<RewardSource, number> = {
    title: 0.98,
    body: 0.96,
    label: 0.9,
    comment: 0.85,
  };

  return {
    value: {
      amount: selected.amount,
      currency: "USD",
      source: selected.source,
      sourceCount: candidates.length,
    },
    confidence: clampConfidence(confidenceBySource[selected.source]),
    evidence: [
      `Explicit USD reward found in ${selected.source}: "${selected.snippet}".`,
      `${candidates.length} explicit reward amount signal(s) found.`,
    ],
  };
}
