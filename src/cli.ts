#!/usr/bin/env node
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { readFileSync, realpathSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { installSkills } from "./install.js";
import { loadCredentials, clearCredentials } from "./auth/credentials.js";
import { runLogin, type AuthMode } from "./auth/login.js";
import { saveCredentials } from "./auth/credentials.js";
import { runSetup } from "./setup.js";
import { runSubmit } from "./submit.js";
import { submitInstallReport } from "./report.js";
import { collectFingerprint } from "./fingerprint.js";
import { isTargetSelector, type TargetSelector } from "./targets.js";

export type { AuthMode };

export type CliCommand =
  | {
      command: "setup";
      target: TargetSelector;
      dryRun: boolean;
      authMode: AuthMode;
      skipSubstep: boolean;
      force: boolean;
    }
  | { command: "login"; authMode: AuthMode }
  | { command: "logout" }
  | { command: "report"; target: TargetSelector }
  | { command: "install"; target: TargetSelector; dryRun: boolean }
  | {
      command: "submit";
      name?: string;
      slug?: string;
      intro?: string;
      repo?: string;
      api?: string;
      health?: string;
      commit?: string;
    }
  | { command: "doctor" }
  | { command: "print-skill" }
  | { command: "help" };

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");

function resolveAuthMode(rest: string[]): AuthMode {
  if (rest.includes("--no-browser")) return "device";
  if (rest.includes("--loopback")) return "loopback";
  return "paste";
}

export function parseArgs(args: string[]): CliCommand {
  const [command = "help", ...rest] = args;

  if (command === "doctor" || command === "print-skill" || command === "logout") {
    return { command };
  }

  if (command === "login") {
    return { command, authMode: resolveAuthMode(rest) };
  }

  if (command === "submit") {
    const flags: {
      name?: string;
      slug?: string;
      intro?: string;
      repo?: string;
      api?: string;
      health?: string;
      commit?: string;
    } = {};
    for (let index = 0; index < rest.length; index += 1) {
      const arg = rest[index];
      const next = rest[index + 1];
      if (arg === "--name") { flags.name = next; index += 1; continue; }
      if (arg === "--slug") { flags.slug = next; index += 1; continue; }
      if (arg === "--intro") { flags.intro = next; index += 1; continue; }
      if (arg === "--repo") { flags.repo = next; index += 1; continue; }
      if (arg === "--api") { flags.api = next; index += 1; continue; }
      if (arg === "--health") { flags.health = next; index += 1; continue; }
      if (arg === "--commit") { flags.commit = next; index += 1; continue; }
      throw new Error(`Unsupported option: ${arg}`);
    }
    return { command: "submit", ...flags };
  }

  if (command !== "install" && command !== "setup" && command !== "report") {
    return { command: "help" };
  }

  let target: TargetSelector = "all";
  let dryRun = false;
  let skipSubstep = false;
  let force = false;

  for (let index = 0; index < rest.length; index += 1) {
    const arg = rest[index];

    if (arg === "--dry-run") {
      dryRun = true;
      continue;
    }
    if (arg === "--no-browser" || arg === "--loopback") {
      continue;
    }
    if (arg === "--skip-substep") {
      skipSubstep = true;
      continue;
    }
    if (arg === "--force") {
      force = true;
      continue;
    }

    if (arg === "--target") {
      const value = rest[index + 1];
      if (!value) {
        throw new Error("Missing value for --target");
      }
      if (!isTargetSelector(value)) {
        throw new Error(`Unsupported target: ${value}`);
      }
      target = value;
      index += 1;
      continue;
    }

    throw new Error(`Unsupported option: ${arg}`);
  }

  if (command === "setup") {
    return { command, target, dryRun, authMode: resolveAuthMode(rest), skipSubstep, force };
  }
  if (command === "report") {
    return { command, target };
  }
  return { command: "install", target, dryRun };
}

export async function runCli(args: string[]): Promise<number> {
  const command = parseArgs(args);

  if (command.command === "help") {
    writeHelp();
    return 0;
  }

  if (command.command === "print-skill") {
    const skill = await readFile(
      join(packageRoot, "skills", "xagt-setup", "SKILL.md"),
      "utf8"
    );
    process.stdout.write(skill);
    return 0;
  }

  if (command.command === "doctor") {
    const npmVersion = await getCommandVersion("npm", ["--version"]);
    process.stdout.write(`Node: ${process.versions.node}\n`);
    process.stdout.write(`npm: ${npmVersion.trim() || "unavailable"}\n`);
    process.stdout.write(`HOME: ${process.env.HOME ?? "not set"}\n`);
    process.stdout.write(`Backend: ${resolveBaseUrl()}\n`);
    process.stdout.write(`Frontend: ${resolveFrontendBase()}\n`);
    const creds = await loadCredentials();
    if (!creds) {
      process.stdout.write("Login: not logged in (run `xagt-plugin login`)\n");
    } else {
      const remaining = creds.accessExpire - Math.floor(Date.now() / 1000);
      const status = remaining > 0 ? `${Math.floor(remaining / 86400)}d remaining` : "expired";
      process.stdout.write(`Login: ${creds.userId} (${status})\n`);
    }
    return 0;
  }

  const baseUrl = resolveBaseUrl();
  const frontendBase = resolveFrontendBase();
  const version = readPackageVersion();

  if (command.command === "login") {
    const existing = await loadCredentials();
    if (existing && existing.accessExpire > Date.now() / 1000) {
      const remainingDays = Math.floor((existing.accessExpire - Date.now() / 1000) / 86400);
      process.stdout.write(`\n  Currently logged in as ${existing.userId} (${remainingDays}d remaining).\n`);
      process.stdout.write("  Re-running OAuth to refresh / switch account...\n");
    } else {
      process.stdout.write("\n  Signing in to X-Agent\n");
    }
    process.stdout.write(`  Backend: ${baseUrl}\n`);
    const credentials = await runLogin({ authMode: command.authMode, baseUrl, frontendBase, version });
    await saveCredentials(credentials);
    process.stdout.write(`\n  ✓ Logged in as ${credentials.userId}\n`);
    process.stdout.write("\n");
    process.stdout.write("  Now go build your callable capability.\n\n");
    process.stdout.write("  Helpful next commands:\n");
    process.stdout.write("    xagt-plugin install --target all   # optional: add skills to your agents\n");
    process.stdout.write("    xagt-plugin doctor                 # check session status\n");
    process.stdout.write("    xagt-plugin submit                 # submit your project (when ready)\n\n");
    return 0;
  }

  if (command.command === "logout") {
    await clearCredentials();
    process.stdout.write("Logged out.\n");
    return 0;
  }

  if (command.command === "setup") {
    const result = await runSetup({
      baseUrl,
      frontendBase,
      cliVersion: version,
      target: command.target,
      dryRun: command.dryRun,
      authMode: command.authMode,
      skipSubstep: command.skipSubstep,
      force: command.force
    });
    for (const item of result.installResults) {
      process.stdout.write(`  ${item.message}\n`);
    }
    for (const step of result.substeps) {
      const icon =
        step.status === "success" || step.status === "already-installed" ? "✓"
        : step.status === "skipped" ? "·"
        : "✗";
      const label =
        step.status === "already-installed" ? "already installed"
        : step.status === "success" ? "success"
        : step.status === "skipped" ? "skipped"
        : `failed${step.error ? ` (${step.error})` : ""}`;
      process.stdout.write(`  ${icon} ${step.name}: ${label}\n`);
    }
    process.stdout.write("\n");
    process.stdout.write(`  ✓ Signed in as ${result.credentials!.userId}\n`);
    const failed = result.substeps.filter((step) => step.status === "failed");
    if (failed.length === 0) {
      process.stdout.write("  ✓ Skills installed in your agents\n\n");
    } else {
      process.stdout.write(`  ⚠ ${failed.length} OKX skill install step(s) failed — registration is complete; retry with:\n`);
      for (const step of failed) {
        process.stdout.write(`      ${step.command}\n`);
      }
      process.stdout.write("\n");
    }
    process.stdout.write("  Now go build your callable capability.\n\n");
    process.stdout.write("  When you're ready to submit:\n");
    process.stdout.write("    xagt-plugin submit\n\n");
    return failed.length === 0 ? 0 : 2;
  }

  if (command.command === "submit") {
    process.stdout.write("\n  Prepare your MCP Hackathon submission\n\n");
    const result = await runSubmit({
      cliVersion: version,
      input: {
        name: command.name,
        slug: command.slug,
        intro: command.intro,
        repo: command.repo,
        api: command.api,
        health: command.health,
        commit: command.commit
      }
    });
    process.stdout.write(`\n  ✓ Generated: ${result.localPath}\n`);
    process.stdout.write(`  ✓ Generated: ${result.localManifestPath}\n\n`);
    process.stdout.write(`  ✓ Generated: ${result.localRightsPath}\n\n`);
    process.stdout.write(`  Submit as a PR to ${result.repoUrl}:\n\n`);
    process.stdout.write(`    1. Fork in browser: ${result.forkUrl}\n\n`);
    process.stdout.write("    2. Clone your fork and create the submission directory:\n\n");
    process.stdout.write("       git clone https://github.com/<your-gh-username>/xagt-plugin\n");
    process.stdout.write("       cd xagt-plugin\n");
    process.stdout.write(`       git checkout -b submit-${result.slug}\n`);
    process.stdout.write(`       mkdir -p submissions/${result.slug}/source submissions/${result.slug}/verification\n`);
    process.stdout.write(`       cp "${result.localPath}" ${result.filename}\n`);
    process.stdout.write(`       cp "${result.localManifestPath}" ${result.manifestFilename}\n`);
    process.stdout.write(`       cp "${result.localRightsPath}" ${result.rightsFilename}\n`);
    process.stdout.write("       # copy your complete, reviewable source into source/\n");
    process.stdout.write("       # add reproducible API evidence to verification/README.md\n");
    process.stdout.write(`       git add submissions/${result.slug}\n`);
    process.stdout.write(`       git commit -m "submit: ${result.slug}"\n`);
    process.stdout.write(`       git push -u origin submit-${result.slug}\n\n`);
    process.stdout.write(`    3. Open a PR against ${result.repoUrl}/compare\n\n`);
    return 0;
  }

  if (command.command === "report") {
    const credentials = await loadCredentials();
    if (!credentials) {
      throw new Error("not logged in");
    }
    const target =
      command.target === "all" ? "generic" : command.target === "cursor" ? "cursor" : command.target === "claude-code" ? "claude-code" : "generic";
    await submitInstallReport({
      baseUrl,
      credentials,
      report: {
        schemaVersion: 1,
        target,
        login: { status: "success", subject: credentials.userId },
        fingerprint: collectFingerprint({ cliVersion: version, agentRuntime: target }),
        substep: { command: "manual-report", status: "skipped", duration: 0 },
        occurredAt: new Date().toISOString()
      }
    });
    process.stdout.write("Report submitted.\n");
    return 0;
  }

  const results = await installSkills({
    target: command.target,
    dryRun: command.dryRun
  });

  for (const result of results) {
    process.stdout.write(`${result.message}\n`);
  }

  return 0;
}

function writeHelp(): void {
  process.stdout.write(`Usage:
  xagt-plugin setup [--target cursor|claude-code|codex|opencode|generic|all] [--force] [--dry-run] [--no-browser] [--loopback] [--skip-substep]
                              # one-shot: registers you + installs OKX skills
  xagt-plugin submit [--name <s>] [--slug <team-project>] [--intro <s>] [--repo <url>] [--api <url>] [--health <url>] [--commit <sha>]
                              # generates a manifest; add it, complete source, and verification evidence in a PR
  xagt-plugin login [--no-browser] [--loopback]   # re-login or switch accounts
  xagt-plugin logout                  # clear local credentials
  xagt-plugin install [--target ...]  # install skills only (no login)
  xagt-plugin doctor                  # show login + runtime status
  xagt-plugin report [--target ...]   # resend install report
  xagt-plugin print-skill             # print SKILL.md to stdout

Auth modes:
  default       paste-code flow (browser → page shows code → paste back)
  --loopback    loopback browser flow (binds a local port, no paste required)
  --no-browser  device-code flow (for SSH / headless environments)

Hackathon flow:
  1. build and deploy a callable capability
  2. xagt-plugin submit                # generate a manifest
  3. submit source + evidence via GitHub PR
`);
}

function getCommandVersion(command: string, args: string[]): Promise<string> {
  return new Promise((resolveVersion) => {
    execFile(command, args, (error: Error | null, stdout: string) => {
      resolveVersion(error ? "" : stdout);
    });
  });
}

function readPackageVersion(): string {
  const raw = readFileSync(join(packageRoot, "package.json"), "utf8");
  const parsed = JSON.parse(raw) as { version?: string };
  return parsed.version ?? "0.0.0";
}

export function resolveBaseUrl(): string {
  return process.env.XAGT_API_BASE ?? "https://api.xerpaai.com";
}

export function resolveFrontendBase(): string {
  return process.env.XAGT_FRONTEND_BASE ?? "https://www.xerpaai.com";
}

function isMainModule(): boolean {
  const entry = process.argv[1];
  if (!entry) return false;
  const here = fileURLToPath(import.meta.url);
  if (entry === here) return true;
  try {
    return realpathSync(entry) === here;
  } catch {
    return false;
  }
}

if (isMainModule()) {
  runCli(process.argv.slice(2)).catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    process.stderr.write(`${message}\n`);
    if (error instanceof Error && error.cause !== undefined && error.cause !== null) {
      const cause = error.cause as { code?: string; message?: string };
      const detail = cause.code ?? cause.message ?? String(cause);
      if (detail) process.stderr.write(`  cause: ${detail}\n`);
    }
    process.exitCode = 1;
  });
}
