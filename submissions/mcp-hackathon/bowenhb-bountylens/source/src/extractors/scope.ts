import type { NormalizedIssueContext } from "../github/normalize.js";
import { clampConfidence, type EvidenceSignal } from "./types.js";

export type ScopeEvidence = {
  hasAcceptanceSection: boolean;
  hasReproductionSection: boolean;
  checklistItemCount: number;
  orderedStepCount: number;
  testSignalCount: number;
  fileReferenceCount: number;
  actionItemCount: number;
  analyzedCharacters: number;
  wasTruncated: boolean;
};

const maximumAnalyzedCharacters = 100_000;
const acceptancePattern = /(?:acceptance criteria|definition of done|验收(?:标准|条件)|criterios? de aceptación)/i;
const reproductionPattern = /(?:steps? to reproduce|how to reproduce|reproduction|复现步骤|重现步骤)/i;
const testPattern = /(?:\bnpm\s+(?:run\s+)?test\b|\bvitest\b|\bpytest\b|\bcargo\s+test\b|\btest(?:s|ing)?\b|测试|回归)/i;
const actionPattern = /(?:\b(?:add|build|create|document|fix|implement|include|remove|run|update|write)\b|添加|创建|实现|修复|更新|删除|运行|编写)/i;
const fileReferencePattern = /`[^`\n]*(?:\/|\.(?:c|cc|cpp|go|js|json|md|py|rs|sh|ts|tsx|yaml|yml))[^`\n]*`/gi;

/** Extract scope clarity signals from the issue text without assigning a score. */
export function extractScope(
  context: Pick<NormalizedIssueContext, "issue">,
): EvidenceSignal<ScopeEvidence> {
  const originalBody = context.issue.body;
  const body = originalBody.slice(0, maximumAnalyzedCharacters);
  const lines = body.split(/\r?\n/);
  const checklistItemCount = lines.filter((line) => /^\s*[-*+]\s+\[[ xX]\]\s+/.test(line)).length;
  const orderedStepCount = lines.filter((line) => /^\s*\d+[.)]\s+/.test(line)).length;
  const testSignalCount = lines.filter((line) => testPattern.test(line)).length;
  const actionItemCount = lines.filter(
    (line) => /^\s*(?:[-*+]|\d+[.)])\s+/.test(line) && actionPattern.test(line),
  ).length;
  const fileReferenceCount = [...body.matchAll(fileReferencePattern)].length;
  const hasAcceptanceSection = acceptancePattern.test(body);
  const hasReproductionSection = reproductionPattern.test(body);
  const signalCount =
    Number(hasAcceptanceSection) +
    Number(hasReproductionSection) +
    checklistItemCount +
    orderedStepCount +
    testSignalCount +
    fileReferenceCount +
    actionItemCount;

  const evidence = [
    `${checklistItemCount} checklist item(s) and ${orderedStepCount} ordered step(s) found.`,
    `${testSignalCount} test signal(s), ${fileReferenceCount} file reference(s), and ${actionItemCount} explicit action item(s) found.`,
  ];
  if (hasAcceptanceSection) evidence.push("An acceptance-criteria section was found.");
  if (hasReproductionSection) evidence.push("A reproduction section was found.");
  if (body.trim().length === 0) evidence.push("The issue body is empty.");

  const baseConfidence = body.trim().length === 0 ? 0.2 : 0.5 + Math.min(signalCount, 10) * 0.045;

  return {
    value: {
      hasAcceptanceSection,
      hasReproductionSection,
      checklistItemCount,
      orderedStepCount,
      testSignalCount,
      fileReferenceCount,
      actionItemCount,
      analyzedCharacters: body.length,
      wasTruncated: originalBody.length > body.length,
    },
    confidence: clampConfidence(baseConfidence),
    evidence,
  };
}
