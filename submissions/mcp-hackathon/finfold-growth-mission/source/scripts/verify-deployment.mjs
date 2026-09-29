import { execFileSync } from "node:child_process";

const base = (process.env.API_BASE_URL ?? "https://api.finfold.app").replace(/\/$/, "");
const expected = process.argv[2] ?? execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
if (!/^[a-f0-9]{40}$/.test(expected)) throw new Error("Expected commit must be a 40-character SHA.");

const [healthResponse, proofResponse] = await Promise.all([
  fetch(`${base}/health`, { signal: AbortSignal.timeout(10_000) }),
  fetch(`${base}/.well-known/xagent-verification.json`, { signal: AbortSignal.timeout(10_000) }),
]);
const health = await healthResponse.json();
const proof = await proofResponse.json();
if (!healthResponse.ok || health.status !== "ok" || health.commit !== expected) {
  throw new Error(`Health verification failed: ${JSON.stringify(health)}`);
}
if (!proofResponse.ok || proof.schemaVersion !== 1 || proof.slug !== "finfold-growth-mission" || proof.commit !== expected) {
  throw new Error(`Ownership proof failed: ${JSON.stringify(proof)}`);
}
console.log(JSON.stringify({ verified: true, base, commit: expected, health, proof }, null, 2));
