import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";

const apiBase = (process.env.API_BASE_URL ?? "https://api.finfold.app").replace(/\/$/, "");
const reviewKey = process.env.REVIEW_KEY;
const sourceUrl = process.env.SOURCE_URL ?? "https://www.finfold.app/";
const count = Number(process.env.BENCHMARK_COUNT ?? 20);
const requestedPlatforms = (process.env.BENCHMARK_PLATFORMS ?? "linkedin,x,reddit,xiaohongshu,wechat")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);
const supportedPlatforms = new Set(["linkedin", "x", "reddit", "xiaohongshu", "wechat"]);
if (!reviewKey) {
  console.error("Set REVIEW_KEY in the process environment. It is never written to the benchmark report.");
  process.exit(2);
}
if (!Number.isInteger(count) || count < 1 || count > 50) {
  console.error("BENCHMARK_COUNT must be an integer from 1 to 50.");
  process.exit(2);
}
if (!requestedPlatforms.length || requestedPlatforms.some((platform) => !supportedPlatforms.has(platform))) {
  console.error("BENCHMARK_PLATFORMS must contain supported comma-separated platform names.");
  process.exit(2);
}

const results = [];
const assetFingerprints = new Set();
for (let index = 0; index < count; index += 1) {
  const started = performance.now();
  let status = 0;
  let errorCode;
  let providerAttempts;
  let evidenceCount;
  let assetLength;
  const platform = requestedPlatforms[index % requestedPlatforms.length];
  try {
    const response = await fetch(`${apiBase}/v1/missions`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${reviewKey}`,
        "content-type": "application/json",
        "idempotency-key": `benchmark-${Date.now()}-${index}`,
      },
      body: JSON.stringify({ sourceUrl, objective: "leads", platform, locale: "en" }),
      signal: AbortSignal.timeout(35_000),
    });
    status = response.status;
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      errorCode = body?.error?.code ?? `HTTP_${response.status}`;
    } else {
      const body = await response.json();
      providerAttempts = body?.provenance?.providerAttempts;
      evidenceCount = Array.isArray(body?.evidence) ? body.evidence.length : undefined;
      assetLength = typeof body?.asset?.body === "string" ? [...body.asset.body].length : undefined;
      if (typeof body?.asset?.body === "string") {
        const normalized = body.asset.body.replace(/https:\/\/api\.finfold\.app\/r\/[a-z0-9]+/g, "{{TRACKING_URL}}");
        assetFingerprints.add(createHash("sha256").update(normalized).digest("hex"));
      }
    }
  } catch (error) {
    errorCode = error instanceof Error ? error.name : "UNKNOWN_ERROR";
  }
  results.push({
    run: index + 1,
    platform,
    status,
    durationMs: Math.round(performance.now() - started),
    ...(providerAttempts ? { providerAttempts } : {}),
    ...(evidenceCount ? { evidenceCount } : {}),
    ...(assetLength ? { assetLength } : {}),
    ...(errorCode ? { errorCode } : {}),
  });
}

const durations = results.map((result) => result.durationMs).sort((a, b) => a - b);
const percentile = (values, value) => values[Math.max(0, Math.ceil(values.length * value) - 1)];
const p50 = percentile(durations, 0.5);
const p95 = durations[Math.max(0, Math.ceil(durations.length * 0.95) - 1)];
const p99 = percentile(durations, 0.99);
const successes = results.filter((result) => result.status >= 200 && result.status < 300).length;
const firstAttemptSuccesses = results.filter(
  (result) => result.status >= 200 && result.status < 300 && result.providerAttempts === 1,
).length;
const summary = {
  generatedAt: new Date().toISOString(),
  apiBase,
  sourceUrl,
  runs: count,
  successes,
  successRate: successes / count,
  firstAttemptSuccessRate: firstAttemptSuccesses / count,
  uniqueValidatedAssets: assetFingerprints.size,
  p50Ms: p50,
  p95Ms: p95,
  p99Ms: p99,
  syncGatePassed: successes / count >= 0.95 && Number(p95) <= 30_000,
  winningTargetPassed: successes / count >= 0.98 && Number(p95) <= 30_000,
  results,
};
await mkdir("benchmark-results", { recursive: true });
const output = `benchmark-results/${new Date().toISOString().replaceAll(":", "-")}.json`;
await writeFile(output, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ ...summary, results: undefined, output }, null, 2));
if (!summary.syncGatePassed) process.exit(1);
