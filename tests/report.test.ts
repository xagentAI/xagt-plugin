import { mkdir, mkdtemp, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { collectFingerprint } from "../src/fingerprint.js";
import { createInstallReport, flushPendingReports, submitInstallReport } from "../src/report.js";

const credentials = {
  accessToken: "access-token",
  refreshToken: "refresh-token",
  accessExpire: 0,
  userId: "user-1"
};

const report = createInstallReport({
  target: "generic",
  login: { status: "success", subject: "user-1" },
  fingerprint: collectFingerprint({ cliVersion: "0.1.0", agentRuntime: "generic" }),
  substep: { command: "install", status: "success", duration: 10 }
});

const temporaryConfigDirs: string[] = [];

afterEach(async () => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  await Promise.all(temporaryConfigDirs.splice(0).map((directory) => rm(directory, { recursive: true, force: true })));
});

async function useTemporaryConfig(): Promise<string> {
  const directory = await mkdtemp(join(tmpdir(), "xagt-report-test-"));
  temporaryConfigDirs.push(directory);
  vi.stubEnv("XDG_CONFIG_HOME", directory);
  return directory;
}

describe("report payload", () => {
  it("creates schema v1 report", () => {
    const fingerprint = collectFingerprint({
      cliVersion: "0.1.0",
      agentRuntime: "generic"
    });
    const report = createInstallReport({
      target: "generic",
      login: { status: "success", subject: "1" },
      fingerprint,
      substep: {
        command: "npx skills add okx/plugin-store --skill plugin-store",
        status: "success",
        duration: 10
      }
    });
    expect(report.schemaVersion).toBe(1);
    expect(report.target).toBe("generic");
    expect(report.substep.status).toBe("success");
  });

  it("keeps a pending report when the initial submit and retry both fail", async () => {
    const configDir = await useTemporaryConfig();
    vi.stubGlobal(
      "fetch",
      vi.fn()
        .mockResolvedValueOnce(new Response(JSON.stringify({ msg: "unavailable" }), { status: 500 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({ msg: "still unavailable" }), { status: 500 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({ success: true }), { status: 200 }))
    );

    await submitInstallReport({ baseUrl: "https://api.example.test", credentials, report });
    const pendingDir = join(configDir, "xagt", "pending-reports");
    const [pendingFile] = await readdir(pendingDir);
    expect(pendingFile).toBeDefined();
    expect(JSON.parse(await readFile(join(pendingDir, pendingFile!), "utf8"))).toEqual(JSON.parse(JSON.stringify(report)));

    await flushPendingReports({ baseUrl: "https://api.example.test", credentials });
    expect(await readdir(pendingDir)).toHaveLength(1);

    await flushPendingReports({ baseUrl: "https://api.example.test", credentials });
    expect(await readdir(pendingDir)).toHaveLength(0);
  });

  it("continues flushing later reports after an earlier report fails", async () => {
    const configDir = await useTemporaryConfig();
    const pendingDir = join(configDir, "xagt", "pending-reports");
    await mkdir(pendingDir, { recursive: true });
    await writeFile(join(pendingDir, "a.json"), JSON.stringify(report), "utf8");
    await writeFile(join(pendingDir, "b.json"), JSON.stringify(report), "utf8");
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ msg: "unavailable" }), { status: 500 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ success: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await flushPendingReports({ baseUrl: "https://api.example.test", credentials });

    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect((await readdir(pendingDir)).sort()).toEqual(["a.json"]);
  });
});
