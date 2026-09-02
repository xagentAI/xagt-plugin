import { describe, expect, it } from "vitest";
import { validateGeneratedMission } from "../src/quality";
import { generatedMissionSchema, type SemanticSection } from "../src/schemas";
import { GENERATED } from "./fixtures";

const sections: SemanticSection[] = [
  {
    id: "s4",
    kind: "paragraph",
    text: "Plan work, review customer evidence, and coordinate launches in one calm workspace.",
  },
];

describe("claim-to-evidence and content quality", () => {
  it("accepts exact evidence and a single tracking CTA", () => {
    const generated = generatedMissionSchema.parse(GENERATED);
    expect(validateGeneratedMission(generated, sections, "leads", "linkedin")).toMatchObject({
      passed: true,
      evidenceExactMatch: true,
    });
  });

  it("accepts individual sentences compiled from one exact multi-sentence quote", () => {
    const quote = "Plan work in one calm workspace. Review customer evidence before launch.";
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      asset: {
        ...GENERATED.asset,
        body: `A product angle worth testing:\n\n${quote}\n\nCould this help? {{TRACKING_URL}}`,
      },
      evidence: [{ id: "e1", sectionId: "s1", quote, confidence: 0.99 }],
      claimMap: [{ claim: quote, evidenceIds: ["e1"] }],
    });
    expect(
      validateGeneratedMission(
        generated,
        [{ id: "s1", kind: "paragraph", text: quote }],
        "leads",
        "linkedin",
      ),
    ).toMatchObject({ passed: true, evidenceExactMatch: true });
  });

  it("rejects a quote that is not an exact source substring", () => {
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      evidence: [{ ...GENERATED.evidence[0], quote: "Coordinate every launch in one workspace." }],
    });
    expect(() => validateGeneratedMission(generated, sections, "leads", "linkedin")).toThrow(/exact substring/);
  });

  it("rejects unsupported numeric claims", () => {
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      asset: { ...GENERATED.asset, body: `${GENERATED.asset.body} Improve conversion by 30%.` },
    });
    expect(() => validateGeneratedMission(generated, sections, "leads", "linkedin")).toThrow(/numbers not present/);
  });

  it("rejects absolute outcome guarantees", () => {
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      asset: { ...GENERATED.asset, body: `${GENERATED.asset.body} Guaranteed growth.` },
    });
    expect(() => validateGeneratedMission(generated, sections, "leads", "linkedin")).toThrow(/guaranteed outcome/);
  });

  it("rejects platform substitution", () => {
    const generated = generatedMissionSchema.parse(GENERATED);
    expect(() => validateGeneratedMission(generated, sections, "leads", "x")).toThrow(/requested platform/);
  });

  it("rejects a mapped claim that is not extractive from its evidence", () => {
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      claimMap: [{ claim: "This workspace guarantees faster launches.", evidenceIds: ["e1"] }],
    });
    expect(() => validateGeneratedMission(generated, sections, "leads", "linkedin")).toThrow(/deliverable|cited evidence/);
  });

  it("rejects an unsupported absolute statement in the asset", () => {
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      asset: { ...GENERATED.asset, body: `${GENERATED.asset.body} This platform improves every launch workflow.` },
    });
    expect(() => validateGeneratedMission(generated, sections, "leads", "linkedin")).toThrow(/neither exact evidence/);
  });

  it("rejects a distribution-platform claim absent from cited evidence", () => {
    const generated = generatedMissionSchema.parse({
      ...GENERATED,
      asset: { ...GENERATED.asset, body: `${GENERATED.asset.body} Test whether this LinkedIn post attracts relevant teams.` },
    });
    expect(() => validateGeneratedMission(generated, sections, "leads", "linkedin")).toThrow(/names linkedin/);
  });
});
