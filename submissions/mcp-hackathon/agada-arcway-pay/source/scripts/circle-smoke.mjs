#!/usr/bin/env node
/**
 * Standalone Circle integration test.
 *
 * Takes the treasury wallet id as an ARGUMENT, deliberately not from the
 * environment: CIRCLE_TREASURY_WALLET_ID is the switch that puts the app into
 * live mode, and it must stay unset until a real transfer has been proven to
 * land here. This script is the only thing allowed to move real funds until
 * then.
 *
 *   node scripts/with-env.mjs node scripts/circle-smoke.mjs \
 *     --wallet <walletId> --to <address> --amount 1.25 [--token erc20|native]
 *
 * Add --dry-run to resolve balances and the token without sending anything.
 */
import { initiateDeveloperControlledWalletsClient } from "@circle-fin/developer-controlled-wallets";

function arg(name, fallback = undefined) {
  const i = process.argv.indexOf(`--${name}`);
  return i !== -1 && process.argv[i + 1] ? process.argv[i + 1] : fallback;
}
const has = (name) => process.argv.includes(`--${name}`);

const walletId = arg("wallet");
const destination = arg("to");
const amount = arg("amount", "1");
const tokenKind = arg("token", "erc20");
const dryRun = has("dry-run");

if (!walletId) {
  console.error("--wallet <treasury wallet id> is required (not read from env on purpose)");
  process.exit(2);
}

const apiKey = process.env.CIRCLE_API_KEY;
const entitySecret = process.env.CIRCLE_ENTITY_SECRET;
if (!apiKey || !entitySecret) {
  console.error("CIRCLE_API_KEY and CIRCLE_ENTITY_SECRET must be set.");
  process.exit(2);
}

const client = initiateDeveloperControlledWalletsClient({ apiKey, entitySecret });

const balances = await client.getWalletTokenBalance({ id: walletId });
const tokens = balances.data?.tokenBalances ?? [];
console.log(`treasury ${walletId}`);
for (const b of tokens) {
  const native = !b.token?.tokenAddress;
  console.log(`  ${String(b.amount).padStart(12)} ${b.token?.symbol}  ${native ? "native" : b.token.tokenAddress}  ${b.token?.decimals}dp  id=${b.token?.id}`);
}

// Arc carries USDC twice: as the native gas asset (18dp) and as an ERC-20
// (6dp). The ERC-20 is the one the app accounts in — 6dp matches
// Decimal(20,6), and lib/balance.ts reads it with an ERC-20 balanceOf.
const pick = tokens.find((b) =>
  b.token?.symbol === "USDC" &&
  (tokenKind === "native" ? !b.token.tokenAddress : Boolean(b.token.tokenAddress))
);
if (!pick) {
  console.error(`No ${tokenKind} USDC balance on this wallet.`);
  process.exit(1);
}
console.log(`\nusing ${tokenKind} USDC  tokenId=${pick.token.id}  available=${pick.amount}`);

if (Number(pick.amount) < Number(amount)) {
  console.error(`Insufficient funds: have ${pick.amount}, asked for ${amount}.`);
  process.exit(1);
}
if (dryRun) {
  console.log("\n--dry-run: stopping before the transfer.");
  process.exit(0);
}
if (!destination) {
  console.error("--to <address> is required to send.");
  process.exit(2);
}

// An idempotency key makes a retried request safe: Circle returns the original
// transaction rather than sending a second one.
const idempotencyKey = crypto.randomUUID();
console.log(`\nsending ${amount} USDC -> ${destination}\n  idempotencyKey ${idempotencyKey}`);

const created = await client.createTransaction({
  walletId,
  tokenId: pick.token.id,
  destinationAddress: destination,
  amounts: [String(amount)],
  fee: { type: "level", config: { feeLevel: "MEDIUM" } },
  idempotencyKey,
});

const tx = created.data;
console.log("  created:", JSON.stringify(tx));

const id = tx?.id;
if (!id) { console.error("No transaction id returned."); process.exit(1); }

// Real transfers do not settle instantly; poll until terminal.
const TERMINAL = new Set(["COMPLETE", "CONFIRMED", "FAILED", "CANCELLED", "DENIED"]);
for (let i = 1; i <= 40; i++) {
  await new Promise((r) => setTimeout(r, 3000));
  const res = await client.getTransaction({ id });
  const t = res.data?.transaction;
  console.log(`  [${String(i).padStart(2)}] state=${t?.state ?? "?"} txHash=${t?.txHash ?? "-"}`);
  if (t?.state && TERMINAL.has(t.state)) {
    console.log("\nFINAL");
    console.log("  state:  ", t.state);
    console.log("  txHash: ", t.txHash ?? "(none)");
    console.log("  amounts:", JSON.stringify(t.amounts));
    console.log("  error:  ", t.errorReason ?? t.errorDetails ?? "(none)");
    process.exit(t.state === "FAILED" || t.state === "DENIED" ? 1 : 0);
  }
}
console.log("\nstill pending after ~2 minutes — not a failure, just slow.");
