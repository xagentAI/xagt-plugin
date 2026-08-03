import { cp, mkdir, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { planInstallTargets, type InstallTarget, type TargetSelector } from "./targets.js";

export interface InstallOptions {
  target: TargetSelector;
  dryRun: boolean;
  cwd?: string;
  home?: string;
}

export interface InstallResult {
  target: InstallTarget;
  destination: string;
  status: "planned" | "installed" | "skipped";
  message: string;
}

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const bundledSkillsRoot = join(packageRoot, "skills");
export const BUNDLED_SKILL_NAMES = ["xagt-setup", "xagt-submit-hackathon"] as const;

export async function installSkills(options: InstallOptions): Promise<InstallResult[]> {
  const cwd = options.cwd ?? process.cwd();
  const home = options.home ?? process.env.HOME;
  const targets = planInstallTargets(options.target);
  const results: InstallResult[] = [];

  for (const target of targets) {
    const baseDirectory = target.base === "home" ? home : cwd;

    if (!baseDirectory) {
      results.push({
        target,
        destination: target.skillsDirectory,
        status: "skipped",
        message: `Skipped ${target.id}: HOME is not set.`
      });
      continue;
    }

    const destination = join(baseDirectory, target.skillsDirectory);

    if (!options.dryRun) {
      await mkdir(destination, { recursive: true });
      for (const skillName of BUNDLED_SKILL_NAMES) {
        await cp(join(bundledSkillsRoot, skillName), join(destination, skillName), {
          recursive: true,
          force: true
        });
      }

      if (target.id === "cursor") {
        await writeCursorManifest(cwd);
      }
    }

    results.push({
      target,
      destination,
      status: options.dryRun ? "planned" : "installed",
      message: `${options.dryRun ? "Would install" : "Installed"} ${BUNDLED_SKILL_NAMES.length} X-Agent skills for ${target.label} at ${destination}`
    });
  }

  return results;
}

async function writeCursorManifest(cwd: string): Promise<void> {
  const manifestDirectory = join(cwd, ".cursor-plugin");
  await mkdir(manifestDirectory, { recursive: true });
  await writeFile(
    join(manifestDirectory, "plugin.json"),
    `${JSON.stringify(
      {
        name: "@xagt/agent-plugin",
        displayName: "XAgent Skill Agent Plugin",
        version: "0.1.0",
        skills: ["../skills"]
      },
      null,
      2
    )}\n`
  );
}
