import { mkdtemp, mkdir, rename, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { describe, expect, it } from "vitest";
import { isPrivateIp, validateSubmissionDirectory } from "../scripts/validate-submission.mjs";

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
