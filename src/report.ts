import { mkdir, readdir, readFile, rm, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { apiPost } from "./api/client.js";
import { getConfigDir, type SavedCredentials } from "./auth/credentials.js";
import type { FingerprintInfo } from "./fingerprint.js";
import type { SubstepResult } from "./install/substep.js";

export interface InstallReportPayload {
  schemaVersion: 1;
  target: "cursor" | "claude-code" | "generic";
  login: { status: "success" | "failed"; subject?: string; error?: string };
  fingerprint: FingerprintInfo;
  substep: {
    command: string;
    status: "success" | "failed" | "skipped";
    exitCode?: number;
    error?: string;
    duration: number;
  };
  occurredAt: string;
}

export function createInstallReport(input: {
  target: "cursor" | "claude-code" | "generic";
  fingerprint: FingerprintInfo;
  substep: SubstepResult | InstallReportPayload["substep"];
  login: { status: "success" | "failed"; subject?: string; error?: string };
}): InstallReportPayload {
  const { command, status, exitCode, error, duration } = input.substep;
  const reportStatus: InstallReportPayload["substep"]["status"] =
    status === "already-installed" ? "success" : status;
  return {
    schemaVersion: 1,
    target: input.target,
    login: input.login,
    fingerprint: input.fingerprint,
    substep: { command, status: reportStatus, exitCode, error, duration },
    occurredAt: new Date().toISOString()
  };
}

export async function submitInstallReport(input: {
  baseUrl: string;
  credentials: SavedCredentials;
  report: InstallReportPayload;
}): Promise<void> {
  try {
    await apiPost(
      "/xagent/plugin/install/report",
      input.report,
      { baseUrl: input.baseUrl, accessToken: input.credentials.accessToken }
    );
  } catch {
    await enqueuePendingReport(input.report);
  }
}

export async function flushPendingReports(input: {
  baseUrl: string;
  credentials: SavedCredentials;
}): Promise<void> {
  const dir = pendingReportsDir();
  const files = await readdir(dir).catch(() => []);
  for (const file of files) {
    const full = join(dir, file);
    try {
      const report = JSON.parse(await readFile(full, "utf8")) as InstallReportPayload;
      await apiPost("/xagent/plugin/install/report", report, {
        baseUrl: input.baseUrl,
        accessToken: input.credentials.accessToken
      });
      await rm(full, { force: true });
    } catch {
      // Keep failed reports for a later CLI run and continue with the queue.
      continue;
    }
  }
}

async function enqueuePendingReport(report: InstallReportPayload): Promise<void> {
  const dir = pendingReportsDir();
  await mkdir(dir, { recursive: true });
  const file = join(dir, `${Date.now()}.json`);
  await writeFile(file, JSON.stringify(report, null, 2), "utf8");
}

function pendingReportsDir(): string {
  return join(getConfigDir(), "pending-reports");
}
