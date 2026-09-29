import { LAUNCHPAD_META } from "../lib/solana/launchpad";
import { compilePromptToStrategy } from "../lib/agents/strategy-compiler";
import { confirmLaunchSchema, confirmTokenSchema } from "../lib/validations";

async function runE2ETests() {
  console.log("=========================================");
  console.log(" MULTIPU EXHAUSTIVE E2E SUITE ");
  console.log("=========================================\n");

  let passed = 0;
  let failed = 0;

  function assert(condition: boolean, msg: string) {
    if (condition) {
      console.log(`✅ PASS: ${msg}`);
      passed++;
    } else {
      console.error(`❌ FAIL: ${msg}`);
      failed++;
    }
  }

  // TEST 1: Launchpads distinct names & no duplicates
  console.log("--- 1. Launchpad Configuration Tests ---");
  const padNames = LAUNCHPAD_META.map((p) => p.name);
  const uniqueNames = new Set(padNames);
  assert(padNames.length === uniqueNames.size, "All launchpad names in LAUNCHPAD_META are unique");
  const sherwoodEntry = LAUNCHPAD_META.find((p) => p.id === "sherwood");
  const ponsEntry = LAUNCHPAD_META.find((p) => p.id === "pons");
  assert(sherwoodEntry?.name === "Sherwood", `Sherwood entry has name 'Sherwood' (got '${sherwoodEntry?.name}')`);
  assert(ponsEntry?.name === "Pons", `Pons entry has name 'Pons' (got '${ponsEntry?.name}')`);
  assert(sherwoodEntry?.id !== ponsEntry?.id, "Sherwood and Pons have distinct IDs");

  // TEST 2: Strategy Compiler Tests
  console.log("\n--- 2. Strategy Compiler Tests ---");
  const solStrategy = compilePromptToStrategy("Scalp fresh Pump.fun memes on Solana with >$5k volume, take profit at +35%, stop loss at -12%");
  assert(solStrategy.rules.chain === "solana", "Solana chain extracted correctly");
  assert(solStrategy.rules.launchpads.includes("pumpfun"), "Pump.fun launchpad extracted");
  assert(solStrategy.rules.takeProfitPct === 35, `Take profit parsed as 35% (got ${solStrategy.rules.takeProfitPct}%)`);
  assert(solStrategy.rules.stopLossPct === 12, `Stop loss parsed as 12% (got ${solStrategy.rules.stopLossPct}%)`);

  const rhStrategy = compilePromptToStrategy("Deploy sniper on Sherwood Robinhood Chain with 0.5 ETH");
  assert(rhStrategy.rules.chain === "robinhood", "Robinhood chain extracted correctly");
  assert(rhStrategy.rules.launchpads.includes("sherwood"), "Sherwood launchpad extracted correctly");

  const bscStrategy = compilePromptToStrategy("Buy trending tokens on Four.meme on BSC");
  assert(bscStrategy.rules.chain === "bsc", "BSC chain extracted correctly");
  assert(bscStrategy.rules.launchpads.includes("fourmeme"), "Four.meme launchpad extracted correctly");

  // TEST 3: Validation Schema Tests (Mock, Demo, Sandbox, and On-Chain)
  console.log("\n--- 3. Validation Schema & Sandbox Format Tests ---");
  const validMockToken = confirmTokenSchema.safeParse({
    tokenId: "123e4567-e89b-12d3-a456-426614174000",
    mintAddress: "mock-mint-abc1234",
    mintTx: "mock-tx-def5678",
  });
  assert(validMockToken.success, "confirmTokenSchema accepts mock/sandbox mint address and tx");

  const validRealToken = confirmTokenSchema.safeParse({
    tokenId: "123e4567-e89b-12d3-a456-426614174000",
    mintAddress: "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
    mintTx: "5rGqV1hK7u6ZtL4gS7mR8sK3nP2vC9xY4dE1wA8bJ5cT3fU9yH6oW2qM1eD7kF4s",
  });
  assert(validRealToken.success, "confirmTokenSchema accepts real base58 Solana mint and tx signature");

  const validMockLaunch = confirmLaunchSchema.safeParse({
    launchId: "123e4567-e89b-12d3-a456-426614174000",
    poolAddress: "mock-pool-999",
    launchTx: "sim_solana_xyz1234",
  });
  assert(validMockLaunch.success, "confirmLaunchSchema accepts mock/sandbox pool address and sim tx");

  const validEvmLaunch = confirmLaunchSchema.safeParse({
    launchId: "123e4567-e89b-12d3-a456-426614174000",
    poolAddress: "0x1234567890123456789012345678901234567890",
    launchTx: "0x" + "a".repeat(64),
  });
  assert(validEvmLaunch.success, "confirmLaunchSchema accepts standard EVM contract and txHash");

  // TEST 4: Runtime Config Testnet / Mainnet Safeguards
  console.log("\n--- 4. Runtime Config Phase Tests ---");
  const { isMainnetNetwork, areEvmLaunchesEnabledOnClient } = await import("../lib/runtime-config");
  const isMainnet = isMainnetNetwork();
  console.log(`Current Solana Network isMainnet: ${isMainnet}`);
  const evmAllowedOnClient = areEvmLaunchesEnabledOnClient();
  assert(typeof evmAllowedOnClient === "boolean", "areEvmLaunchesEnabledOnClient returns boolean without crashing");
  console.log(`EVM launches permitted in current environment: ${evmAllowedOnClient}`);

  // TEST 5: KeeperHub Shield Offline Dry-Run Verification
  console.log("\n--- 5. KeeperHub Shield Dry-Run Tests ---");
  const { dryRunWorkflow, executeKeeperHubWorkflow } = await import("../lib/keeperhub/client");
  const dryRunRes = await dryRunWorkflow({
    chain: "solana",
    action: "bonding_curve_swap",
    sender: "demo_wallet",
    amount: 0.2,
    data: { tokenSymbol: "PEPEQ" },
  });
  assert(dryRunRes.success === true, "KeeperHub dry-run allows transaction with valid simulation");
  assert(dryRunRes.mevRiskScore === "LOW" || dryRunRes.mevRiskScore === "MEDIUM", `KeeperHub MEV risk score safe: ${dryRunRes.mevRiskScore}`);

  const keeperExecRes = await executeKeeperHubWorkflow({
    chain: "solana",
    action: "bonding_curve_swap",
    sender: "demo_wallet",
    amount: 0.1,
    data: { tokenSymbol: "PEPEQ", launchpad: "pumpfun", tradeAction: "buy" },
  });
  assert(keeperExecRes.status === "confirmed", "KeeperHub workflow executes and confirms");
  assert(keeperExecRes.txHash.length > 0, `KeeperHub returns transaction hash: ${keeperExecRes.txHash}`);

  console.log("\n=========================================");
  console.log(` RESULTS: ${passed} PASSED, ${failed} FAILED `);
  console.log("=========================================\n");

  if (failed > 0) {
    process.exit(1);
  }
}

runE2ETests().catch((err) => {
  console.error("Test runner crashed:", err);
  process.exit(1);
});
