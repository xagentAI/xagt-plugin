import { access, mkdtemp, readFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { BUNDLED_SKILL_NAMES, installSkills } from "../src/install.js";

describe("skill installation", () => {
  it("installs setup and hackathon submission skills with bundled metadata", async () => {
    const home = await mkdtemp(join(tmpdir(), "xagt-skills-home-"));
    const cwd = await mkdtemp(join(tmpdir(), "xagt-skills-cwd-"));

    const [result] = await installSkills({ target: "codex", dryRun: false, home, cwd });

    expect(BUNDLED_SKILL_NAMES).toEqual(["xagt-setup", "xagt-submit-hackathon"]);
    expect(result.status).toBe("installed");
    expect(result.destination).toBe(join(home, ".codex", "skills"));
    expect(result.message).toContain("2 X-Agent skills");

    const setup = await readFile(join(result.destination, "xagt-setup", "SKILL.md"), "utf8");
    const submit = await readFile(join(result.destination, "xagt-submit-hackathon", "SKILL.md"), "utf8");
    expect(setup).toContain("name: xagt-setup");
    expect(submit).toContain("name: xagt-submit-hackathon");
    await access(join(result.destination, "xagt-submit-hackathon", "agents", "openai.yaml"));
  });

  it("plans both skills without writing in dry-run mode", async () => {
    const home = await mkdtemp(join(tmpdir(), "xagt-skills-dry-home-"));
    const cwd = await mkdtemp(join(tmpdir(), "xagt-skills-dry-cwd-"));

    const [result] = await installSkills({ target: "claude-code", dryRun: true, home, cwd });

    expect(result.status).toBe("planned");
    expect(result.message).toContain("Would install 2 X-Agent skills");
    await expect(access(join(home, ".claude", "skills"))).rejects.toThrow();
  });
});
