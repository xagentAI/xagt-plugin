import { createHash } from "node:crypto";
import { PrivyClient } from "@privy-io/server-auth";

/**
 * Server-side embedded wallet provisioning, via Privy.
 *
 * This is the "Privy track" half of the submission: when a company adds a
 * payee by email, we ask Privy to create (or fetch, if it already exists) a
 * Privy user for that email address with a pregenerated embedded Ethereum
 * wallet — *before* the payee has ever visited the app or signed anything.
 * The payee can later claim that account by logging in with the same email
 * on Privy's login flow and will find the wallet (and its funds) waiting.
 *
 * Docs: https://docs.privy.io/wallets/using-wallets/pregenerated/overview
 * SDK:  @privy-io/server-auth (note: Privy's docs also point newer projects
 *       at @privy-io/node; we use server-auth here since it's the SDK this
 *       project was scoped around and it's still fully supported).
 *
 * MOCK MODE: if PRIVY_APP_ID / PRIVY_APP_SECRET are not set, we skip the
 * network call entirely and deterministically derive a fake-but-stable
 * 0x... address from the payee's email, so the UI and demo flow work
 * end-to-end with zero external accounts.
 */

export const isPrivyConfigured = Boolean(
  process.env.PRIVY_APP_ID && process.env.PRIVY_APP_SECRET
);

let cachedClient: PrivyClient | null = null;

function getPrivyClient(): PrivyClient {
  if (!isPrivyConfigured) {
    throw new Error(
      "Privy is not configured. Set PRIVY_APP_ID and PRIVY_APP_SECRET."
    );
  }
  if (!cachedClient) {
    cachedClient = new PrivyClient(
      process.env.PRIVY_APP_ID as string,
      process.env.PRIVY_APP_SECRET as string
    );
  }
  return cachedClient;
}

/** Deterministic fake address for demo/mock mode: 0x + 40 hex chars derived from the email. */
function mockWalletAddress(email: string): string {
  const hash = createHash("sha256").update(email.toLowerCase()).digest("hex");
  return `0x${hash.slice(0, 40)}`;
}

export interface ProvisionedWallet {
  address: string;
  /** Privy's user id (DID) for this payee, if a real Privy call was made. */
  privyUserId?: string;
  mocked: boolean;
}

/**
 * Provisions (or looks up) an embedded wallet for a payee identified only
 * by email. No wallet install, no seed phrase, nothing for the payee to do.
 */
export async function provisionEmbeddedWallet(
  email: string
): Promise<ProvisionedWallet> {
  if (!isPrivyConfigured) {
    // --- MOCK MODE ---
    // Simulate a small amount of network latency so the UI's loading state
    // is exercised the same way it would be with the real API.
    await new Promise((resolve) => setTimeout(resolve, 250));
    return { address: mockWalletAddress(email), mocked: true };
  }

  // --- REAL PRIVY CALL ---
  // `importUser` creates a Privy user pre-linked to this email address and,
  // with `createEthereumWallet: true`, provisions a pregenerated embedded
  // wallet for them in the same call. If a user with this email already
  // exists, handle that case below by looking them up instead.
  const privy = getPrivyClient();

  try {
    const user = await privy.importUser({
      linkedAccounts: [{ type: "email", address: email }],
      createEthereumWallet: true,
    });

    const walletAddress = user.wallet?.address;
    if (!walletAddress) {
      throw new Error("Privy did not return an embedded wallet address.");
    }

    return { address: walletAddress, privyUserId: user.id, mocked: false };
  } catch (err) {
    // Most likely cause: a Privy user for this email already exists.
    // Fall back to looking the user up and creating a wallet for them if
    // they don't already have one. (`getUserByEmail` / `createWallets` are
    // both part of @privy-io/server-auth's PrivyClient — see its type defs
    // for the exact shape, since this surface evolves with SDK versions.)
    const existing = await privy.getUserByEmail(email).catch(() => null);
    if (existing?.wallet?.address) {
      return {
        address: existing.wallet.address,
        privyUserId: existing.id,
        mocked: false,
      };
    }
    if (existing) {
      const updated = await privy.createWallets({
        userId: existing.id,
        createEthereumWallet: true,
      });
      if (updated.wallet?.address) {
        return {
          address: updated.wallet.address,
          privyUserId: updated.id,
          mocked: false,
        };
      }
    }
    throw err;
  }
}
