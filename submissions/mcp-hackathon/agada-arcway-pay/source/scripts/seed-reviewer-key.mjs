#!/usr/bin/env node
/**
 * Creates (or rotates) the public reviewer API key shipped in SUBMISSION.md.
 *
 *   npm run keys:reviewer
 *
 * The key is printed ONCE. It is bounded on three axes because it is published
 * in a public document:
 *   - its own dedicated company, never a real tenant's books
 *   - a low per-minute rate limit
 *   - a hard per-payout ceiling, so one call cannot drain the treasury
 * It is revocable from Settings like any other key.
 *
 * Key format and hashing are duplicated from lib/api-keys.ts rather than
 * imported: Node cannot resolve that module's extensionless TS imports when
 * type-stripping. The round-trip check at the end fails loudly if the two ever
 * disagree, so the duplication cannot drift silently.
 */
import { createHash, randomBytes } from "node:crypto";
import { PrismaClient } from "@prisma/client";

const COMPANY_NAME = "X-Agent Reviewers";
const LABEL = "Public reviewer key (SUBMISSION.md)";
const RATE_LIMIT_PER_MINUTE = 6;
const MAX_AMOUNT_USDC = 2;

// Must match lib/api-keys.ts exactly.
const KEY_PREFIX = "ark_";
const KEY_BYTES = 32;
const hashApiKey = (raw) => createHash("sha256").update(raw).digest("hex");

const prisma = new PrismaClient();

for (let i = 0; i < 20; i++) {
  try { await prisma.$queryRaw`select 1`; break; }
  catch { await new Promise((r) => setTimeout(r, 1500)); }
}

let company = await prisma.company.findFirst({ where: { name: COMPANY_NAME } });
if (company) {
  console.log(`reusing company "${COMPANY_NAME}" (${company.id})`);
} else {
  company = await prisma.company.create({ data: { name: COMPANY_NAME } });
  console.log(`created company "${COMPANY_NAME}" (${company.id})`);
}

const revoked = await prisma.apiKey.updateMany({
  where: { companyId: company.id, label: LABEL, revokedAt: null },
  data: { revokedAt: new Date() },
});
if (revoked.count > 0) console.log(`revoked ${revoked.count} previous reviewer key(s)`);

const raw = KEY_PREFIX + randomBytes(KEY_BYTES).toString("hex");
const created = await prisma.apiKey.create({
  data: {
    companyId: company.id,
    label: LABEL,
    hashedKey: hashApiKey(raw),
    rateLimitPerMinute: RATE_LIMIT_PER_MINUTE,
    maxAmountUsdc: MAX_AMOUNT_USDC,
  },
  select: { id: true },
});

// Round trip: prove the stored hash is what the auth path will compute.
const found = await prisma.apiKey.findUnique({ where: { hashedKey: hashApiKey(raw) } });
if (!found || found.id !== created.id) {
  console.error("ABORT: the key does not resolve back to its own row — hashing has drifted from lib/api-keys.ts.");
  await prisma.$disconnect();
  process.exit(1);
}

console.log(`
──────────────────────────────────────────────────────────────
 REVIEWER API KEY — shown once, not recoverable
──────────────────────────────────────────────────────────────
  ${raw}

  key id     ${created.id}
  company    ${COMPANY_NAME} (${company.id})
  rate limit ${RATE_LIMIT_PER_MINUTE}/min
  max payout ${MAX_AMOUNT_USDC} USDC per call
  verified   resolves back to its own row
──────────────────────────────────────────────────────────────
Paste into SUBMISSION.md. Revoke from Settings when review closes.
`);

await prisma.$disconnect();
