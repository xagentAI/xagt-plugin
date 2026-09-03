import { mkdtemp, mkdir, rename, writeFile, symlink, rm, readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import {
  isPrivateIp,
  findChangedSubmissionDirectory,
  resolveChangedSubmissionDirectory,
  validateSubmissionDirectory
} from "../scripts/validate-submission.mjs";

const commit = "0123456789abcdef0123456789abcdef01234567";

async function createSubmission({ slug = "team-real-api", source = "export const value = 1;\n" } = {}) {
  const root = await mkdtemp(join(tmpdir(), "xagt-submission-"));
  const directory = join(root, slug);
  await mkdir(join(directory, "source"), { recursive: true });
  await mkdir(join(directory, "verification"), { recursive: true });
  await writeFile(join(directory, "SUBMISSION.md"), "# Real API\n", "utf8");
  await writeFile(join(directory, "RIGHTS.md"), "# Rights\nAuthorized for archive and review.\n", "utf8");
  await writeFile(join(directory, "source", "index.js"), source, "utf8");
  await writeFile(join(directory, "verification", "README.md"), "# Health\n```bash\ncurl https://api.example.com/health\n```\n", "utf8");
  await writeFile(join(directory, "submission.json"), `${JSON.stringify({
    schemaVersion: 1,
    name: "Real API",
    slug,
    sourceRepository: "https://github.com/example/real-api",
    reviewCommit: commit,
    apiBaseUrl: "https://api.example.com/v1",
    healthCheckUrl: "https://api.example.com/health",
    deploymentProofUrl: "https://api.example.com/.well-known/xagent-verification.json"
  }, null, 2)}\n`, "utf8");
  return directory;
}

describe("submission validator", () => {
  it("counts deletions outside the submission directory", async () => {
    const root = await mkdtemp(join(tmpdir(), "xagt-scope-"));
    const git = (...args) => execFileSync("git", ["-C", root, ...args], { encoding: "utf8" }).trim();
    try {
      git("init", "-q");
      git("config", "user.email", "test@example.invalid");
      git("config", "user.name", "Test");
      await writeFile(join(root, "README.md"), "Keep this file\n");
      git("add", ".");
      git("commit", "-qm", "base");
      const base = git("rev-parse", "HEAD");
      await rm(join(root, "README.md"));
      await mkdir(join(root, "submissions/mcp-hackathon/team-api/source"), { recursive: true });
      await writeFile(join(root, "submissions/mcp-hackathon/team-api/source/index.js"), "export const value = 1;\n");
      git("add", "-A");
      git("commit", "-qm", "candidate");
      expect(() => findChangedSubmissionDirectory(root, base, git("rev-parse", "HEAD"))).toThrow(/one project directory/);
    } finally {
      await rm(root, { recursive: true, force: true });
    }
  });

  it("rejects documentation-only source and Git LFS pointers", async () => {
    const directory = await createSubmission();
    await rename(join(directory, "source/index.js"), join(directory, "source/README.md"));
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/implementation/);
    await rename(join(directory, "source/README.md"), join(directory, "source/index.js"));
    await writeFile(join(directory, "source/index.js"), "version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 100\n");
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/LFS/);
  });

  it("rejects symlinked source roots and required documents", async () => {
    const directory = await createSubmission();
    await rename(join(directory, "source"), join(directory, "saved-source"));
    await symlink("saved-source", join(directory, "source"));
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/symbolic links/);
    await rm(join(directory, "source"));
    await rename(join(directory, "saved-source"), join(directory, "source"));
    await rename(join(directory, "RIGHTS.md"), join(directory, "saved-rights.md"));
    await symlink("saved-rights.md", join(directory, "RIGHTS.md"));
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/symbolic links/);
  });

  it("scans verification documents and large source files for secrets", async () => {
    const directory = await createSubmission();
    const evidence = join(directory, "verification/README.md");
    const original = await readFile(evidence, "utf8");
    await writeFile(evidence, `${original}\nsk-abcdefghijklmnopqrstuvwxyz123456\n`);
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/possible secret/);
    await writeFile(evidence, original);
    await writeFile(join(directory, "source/index.js"), `${" ".repeat(1024 * 1024 + 1)}sk-abcdefghijklmnopqrstuvwxyz123456`);
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/possible secret/);
  });

  it("rejects path traversal in scope metadata", () => {
    expect(() => resolveChangedSubmissionDirectory("/repo", ["submissions/mcp-hackathon/team-api/../../README.md"])).toThrow(/path/);
  });
  it("isolates current submissions from historical archive paths", () => {
    expect(resolveChangedSubmissionDirectory("/repo", [
      "submissions/mcp-hackathon/team-real-api/SUBMISSION.md",
      "submissions/mcp-hackathon/team-real-api/source/index.js"
    ])).toBe("/repo/submissions/mcp-hackathon/team-real-api");

    expect(() => resolveChangedSubmissionDirectory("/repo", [
      "submissions/2054060038305091584-meme-radar/META.md"
    ])).toThrow(/submissions\/mcp-hackathon/);
  });

  it("rejects a pull request that changes more than one current project", () => {
    expect(() => resolveChangedSubmissionDirectory("/repo", [
      "submissions/mcp-hackathon/team-one/SUBMISSION.md",
      "submissions/mcp-hackathon/team-two/SUBMISSION.md"
    ])).toThrow(/exactly one project directory/i);
  });

  it("accepts a complete offline submission package", async () => {
    const directory = await createSubmission();
    const report = await validateSubmissionDirectory(directory);
    expect(report.status).toBe("pass");
    expect(report.checks).toHaveLength(3);
  });

  it("rejects a likely committed secret", async () => {
    const directory = await createSubmission({ source: "const token = 'sk-abcdefghijklmnopqrstuvwxyz123456';\n" });
    await expect(validateSubmissionDirectory(directory)).rejects.toThrow(/possible secret/i);
  });

  it("rejects a manifest copied into a different project directory", async () => {
    const directory = await createSubmission({ slug: "team-original-project" });
    const copiedDirectory = join(dirname(directory), "team-fake-project");
    await rename(directory, copiedDirectory);
    await expect(validateSubmissionDirectory(copiedDirectory)).rejects.toThrow(/match the directory/i);
  });

  it("classifies local and private network addresses", () => {
    expect(isPrivateIp("127.0.0.1")).toBe(true);
    expect(isPrivateIp("10.1.2.3")).toBe(true);
    expect(isPrivateIp("192.168.1.1")).toBe(true);
    expect(isPrivateIp("8.8.8.8")).toBe(false);
    expect(isPrivateIp("::1")).toBe(true);
  });

  it("accepts online evidence only when health and proof bind to the review commit", async () => {
    const directory = await createSubmission();
    const report = await validateSubmissionDirectory(directory, {
      online: true,
      commitVerifier: async (_repository, actualCommit) => {
        expect(actualCommit).toBe(commit);
      },
      jsonRequester: async (url) => ({
        headers: {},
        body: url.endsWith("/health")
          ? { status: "ok", commit }
          : { schemaVersion: 1, slug: "team-real-api", commit }
      })
    });
    expect(report.checks).toHaveLength(6);
  });

  it("rejects a live service that reports a different commit", async () => {
    const directory = await createSubmission();
    await expect(validateSubmissionDirectory(directory, {
      online: true,
      commitVerifier: async () => undefined,
      jsonRequester: async (url) => ({
        headers: {},
        body: url.endsWith("/health")
          ? { status: "ok", commit: "f".repeat(40) }
          : { schemaVersion: 1, slug: "team-real-api", commit }
      })
    })).rejects.toThrow(/exact review commit/i);
  });
});
