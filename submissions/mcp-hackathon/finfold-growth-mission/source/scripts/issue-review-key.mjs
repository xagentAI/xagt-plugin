import { createHash, randomBytes, randomUUID } from "node:crypto";
import { spawnSync } from "node:child_process";

const mode = process.argv.includes("--remote") ? "--remote" : process.argv.includes("--local") ? "--local" : undefined;
if (!mode) {
  console.error("Usage: node scripts/issue-review-key.mjs --remote|--local");
  process.exit(2);
}

const raw = `ff_gm_${randomBytes(32).toString("base64url")}`;
const hash = createHash("sha256").update(raw).digest("hex");
const keyId = `key_${randomUUID().replaceAll("-", "")}`;
const now = new Date().toISOString();
const expires = "2026-10-05T23:59:59.000Z";
const sql = [
  "INSERT INTO api_keys (id, token_hash, label, scopes, daily_limit, expires_at, created_at)",
  `VALUES ('${keyId}', '${hash}', 'xagent-review', 'mission:create mission:read outcome:write', 100, '${expires}', '${now}');`,
].join(" ");

const result = spawnSync(
  "npx",
  ["wrangler", "d1", "execute", "finfold-growth-mission", mode, "--command", sql],
  { cwd: process.cwd(), encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] },
);
if (result.status !== 0) {
  console.error(result.stderr || result.stdout || "Review key issuance failed.");
  process.exit(result.status ?? 1);
}
console.log(result.stdout.trim());
console.log("\nReview key (shown once; store it in an approved password manager):");
console.log(raw);
console.log(`Expires: ${expires}; daily limit: 100; scopes: mission:create mission:read outcome:write`);
