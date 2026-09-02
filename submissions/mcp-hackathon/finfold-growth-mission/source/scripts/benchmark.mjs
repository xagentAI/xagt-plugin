import { mkdir, writeFile } from "node:fs/promises";

const apiBase = (process.env.API_BASE_URL ?? "https://api.finfold.app").replace(/\/$/, "");
const reviewKey = process.env.REVIEW_KEY;
const sourceUrl = process.env.SOURCE_URL ?? "https://www.finfold.app/";
const count = Number(process.env.BENCHMARK_COUNT ?? 20);
if (!reviewKey) {
  console.error("Set REVIEW_KEY in the process environment. It is never written to the benchmark report.");
  process.exit(2);
}
if (!Number.isInteger(count) || count < 1 || count > 50) {
  console.error("BENCHMARK_COUNT must be an integer from 1 to 50.");
  process.exit(2);
}

const results = [];
for (let index = 0; index < count; index += 1) {
  const started = performance.now();
  let status = 0;
  let errorCode;
  try {
    const response = await fetch(`${apiBase}/v1/missions`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${reviewKey}`,
        "content-type": "application/json",
        "idempotency-key": `benchmark-${Date.now()}-${index}`,
      },
      body: JSON.stringify({ sourceUrl, objective: "leads", platform: "linkedin", locale: "en" }),
      signal: AbortSignal.timeout(35_000),
    });
    status = response.status;
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      errorCode = body?.error?.code ?? `HTTP_${response.status}`;
    } else {
      await response.arrayBuffer();
    }
  } catch (error) {
    errorCode = error instanceof Error ? error.name : "UNKNOWN_ERROR";
  }
  results.push({ run: index + 1, status, durationMs: Math.round(performance.now() - started), ...(errorCode ? { errorCode } : {}) });
}

const durations = results.map((result) => result.durationMs).sort((a, b) => a - b);
const p95 = durations[Math.max(0, Math.ceil(durations.length * 0.95) - 1)];
const successes = results.filter((result) => result.status >= 200 && result.status < 300).length;
const summary = {
  generatedAt: new Date().toISOString(),
  apiBase,
  sourceUrl,
  runs: count,
  successes,
  successRate: successes / count,
  p95Ms: p95,
  syncGatePassed: successes / count >= 0.95 && Number(p95) <= 30_000,
  results,
};
await mkdir("benchmark-results", { recursive: true });
const output = `benchmark-results/${new Date().toISOString().replaceAll(":", "-")}.json`;
await writeFile(output, `${JSON.stringify(summary, null, 2)}\n`, "utf8");
console.log(JSON.stringify({ ...summary, results: undefined, output }, null, 2));
if (!summary.syncGatePassed) process.exit(1);
