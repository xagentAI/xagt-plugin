import { readFile } from "node:fs/promises";
import { describe, expect, it } from "vitest";

describe("xagt-setup skill", () => {
  it("documents required setup behavior", async () => {
    const skill = await readFile("skills/xagt-setup/SKILL.md", "utf8");
    expect(skill).toMatch(/name: xagt-setup/);
    expect(skill).toMatch(/npx skills add okx\/plugin-store --skill plugin-store/);
    expect(skill).toMatch(/not part of this plugin/);
    expect(skill).toMatch(/OAuth/);
    expect(skill).toMatch(/report/i);
  });
});

describe("xagt-submit-hackathon skill", () => {
  it("requires verifiable evidence and preserves publish authorization boundaries", async () => {
    const skill = await readFile("skills/xagt-submit-hackathon/SKILL.md", "utf8");
    expect(skill).toMatch(/name: xagt-submit-hackathon/);
    expect(skill).toMatch(/Never invent a URL, response, Commit, test result, ownership claim, or deployment state/);
    expect(skill).toMatch(/explicitly authorizes publishing/);
    expect(skill).toMatch(/--online/);
    expect(skill).toMatch(/submissions\/mcp-hackathon\/<slug>/);
  });

  it("has valid Codex interface metadata", async () => {
    const metadata = await readFile("skills/xagt-submit-hackathon/agents/openai.yaml", "utf8");
    expect(metadata).toMatch(/display_name: "Submit to X-Agent Hackathon"/);
    expect(metadata).toMatch(/\$xagt-submit-hackathon/);
  });

  it("routes Codex and Claude Code through the shared submission contract", async () => {
    const agents = await readFile("AGENTS.md", "utf8");
    const claude = await readFile("CLAUDE.md", "utf8");
    const guide = await readFile("docs/agent-submission-guide.md", "utf8");

    expect(agents).toContain("skills/xagt-submit-hackathon/SKILL.md");
    expect(agents).toMatch(/explicitly asks to submit or otherwise authorizes publishing/);
    expect(claude).toContain("@AGENTS.md");
    expect(guide).toMatch(/Codex, Claude Code, Cursor, OpenCode/);
    expect(guide).toMatch(/Do not fabricate API responses/);
  });
});
