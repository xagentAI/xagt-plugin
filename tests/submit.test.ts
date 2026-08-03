import { describe, expect, it } from "vitest";
import { mkdtemp } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { parseArgs } from "../src/cli.js";
import { renderManifest, renderMarkdown, renderRightsDeclaration, runSubmit } from "../src/submit.js";

const payload = {
  name: "Useful capability",
  slug: "team-useful-capability",
  intro: "Completes a real task through a live API.",
  repo: "https://github.com/example/useful-capability",
  api: "https://api.example.com/v1",
  health: "https://api.example.com/health",
  commit: "a".repeat(40)
};

describe("MCP Hackathon submission", () => {
  it("parses live API and source-verification flags", () => {
    expect(
      parseArgs([
        "submit", "--name", payload.name, "--slug", payload.slug, "--intro", payload.intro,
        "--repo", payload.repo, "--api", payload.api, "--health", payload.health, "--commit", payload.commit
      ])
    ).toEqual({ command: "submit", ...payload });
  });

  it("renders the source, API, commit, and verification contract", () => {
    const markdown = renderMarkdown(payload, "0.4.0");
    expect(markdown).toContain("**API base URL:** https://api.example.com/v1");
    expect(markdown).toContain("**Review commit:** `aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa`");
    expect(markdown).toContain("`source/`");
    expect(markdown).toContain("`verification/README.md`");
  });

  it("renders a machine-readable deployment proof contract", () => {
    const manifest = JSON.parse(renderManifest(payload, "0.4.0"));
    expect(manifest).toMatchObject({
      schemaVersion: 1,
      slug: payload.slug,
      reviewCommit: payload.commit,
      healthCheckUrl: payload.health,
      deploymentProofUrl: "https://api.example.com/.well-known/xagent-verification.json"
    });
  });

  it("renders the retention rights declaration required before reward", () => {
    const rights = renderRightsDeclaration(payload);
    expect(rights).toContain("does not revoke the official archive rights");
    expect(rights).toContain(payload.slug);
  });

  it("places new projects in the MCP Hackathon namespace", async () => {
    const outputDir = await mkdtemp(join(tmpdir(), "xagt-submit-output-"));
    const result = await runSubmit({
      cliVersion: "0.4.0",
      input: payload,
      outputDir
    });
    expect(result.filename).toBe("submissions/mcp-hackathon/team-useful-capability/SUBMISSION.md");
    expect(result.manifestFilename).toBe("submissions/mcp-hackathon/team-useful-capability/submission.json");
    expect(result.rightsFilename).toBe("submissions/mcp-hackathon/team-useful-capability/RIGHTS.md");
  });
});
