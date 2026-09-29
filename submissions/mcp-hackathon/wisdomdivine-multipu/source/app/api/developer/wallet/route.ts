import { getAuth, getClientIp } from "@/lib/auth";
import { apiLimiter } from "@/lib/rate-limit";
import { createAdminSupabase } from "@/lib/supabase/server";
import { Connection, PublicKey, Keypair } from "@solana/web3.js";
import { SOLANA_RPC_URL } from "@/lib/solana";
import { Wallet } from "ethers";
import bs58 from "bs58";

import crypto from "crypto";

function getVaultKey(): Buffer {
  const secret = process.env.SESSION_SECRET || process.env.JWT_SECRET;
  if (!secret) {
    if (process.env.NODE_ENV === "production") {
      throw new Error("Missing SESSION_SECRET or JWT_SECRET for secure wallet vault");
    }
    return crypto.createHash("sha256").update("multipu-dev-vault-seed").digest();
  }
  return crypto.createHash("sha256").update(secret).digest();
}

function encrypt(text: string): string {
  const iv = crypto.randomBytes(12);
  const cipher = crypto.createCipheriv("aes-256-gcm", getVaultKey(), iv);
  let encrypted = cipher.update(text, "utf8", "hex");
  encrypted += cipher.final("hex");
  const authTag = cipher.getAuthTag();
  return `${iv.toString("hex")}:${authTag.toString("hex")}:${encrypted}`;
}

function decrypt(cipherPayload: string): string {
  const parts = cipherPayload.split(":");
  if (parts.length === 3) {
    const [ivHex, authTagHex, encrypted] = parts;
    const decipher = crypto.createDecipheriv("aes-256-gcm", getVaultKey(), Buffer.from(ivHex, "hex"));
    decipher.setAuthTag(Buffer.from(authTagHex, "hex"));
    let decrypted = decipher.update(encrypted, "hex", "utf8");
    decrypted += decipher.final("utf8");
    return decrypted;
  }
  // Fallback for legacy format
  const textBytes = Buffer.from(cipherPayload, "base64");
  const keyBytes = getVaultKey();
  const result = Buffer.alloc(textBytes.length);
  for (let i = 0; i < textBytes.length; i++) {
    result[i] = textBytes[i] ^ keyBytes[i % keyBytes.length];
  }
  return result.toString("utf8");
}

export async function GET(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const supabase = createAdminSupabase();
    
    // Fetch user record
    const { data: user } = await supabase
      .from("users")
      .select("id")
      .eq("wallet_address", auth.walletAddress)
      .single();

    if (!user) {
      return Response.json({ error: "User not found" }, { status: 404 });
    }

    // Get current network type based on auth kind
    const network = auth.walletKind === "solana" ? "solana" : "evm";

    // Fetch developer wallet
    let { data: devWallet } = await supabase
      .from("developer_wallets")
      .select("*")
      .eq("user_id", user.id)
      .eq("network", network)
      .single();

    // If none exists, auto-generate one
    if (!devWallet) {
      let publicKey = "";
      let secretKey = "";

      if (network === "solana") {
        const kp = Keypair.generate();
        publicKey = kp.publicKey.toBase58();
        secretKey = bs58.encode(kp.secretKey);
      } else {
        const wall = Wallet.createRandom();
        publicKey = wall.address;
        secretKey = wall.privateKey;
      }

      const { data: newWallet, error: insertErr } = await supabase
        .from("developer_wallets")
        .insert({
          user_id: user.id,
          wallet_address: auth.walletAddress,
          network,
          public_key: publicKey,
          encrypted_private_key: encrypt(secretKey),
        })
        .select()
        .single();

      if (insertErr || !newWallet) {
        throw new Error(insertErr?.message || "Failed to save auto-generated wallet");
      }
      devWallet = newWallet;
    }

    // Query live balance from node connection if Solana
    let balance = 0;
    if (network === "solana") {
      try {
        const connection = new Connection(SOLANA_RPC_URL, "confirmed");
        const balanceLamports = await connection.getBalance(new PublicKey(devWallet.public_key));
        balance = balanceLamports / 1e9;
      } catch (balErr) {
        console.warn("Could not query Solana live balance:", balErr);
      }
    } else {
      try {
        const bscRpc = process.env.NEXT_PUBLIC_BSC_RPC_URL || "https://bsc-dataseed.binance.org";
        const res = await fetch(bscRpc, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            jsonrpc: "2.0",
            method: "eth_getBalance",
            params: [devWallet.public_key, "latest"],
            id: 1,
          }),
        });
        if (res.ok) {
          const json = await res.json();
          if (json.result) {
            balance = Number(BigInt(json.result) / BigInt(10 ** 12)) / 1e6;
          }
        }
      } catch (balErr) {
        console.warn("Could not query EVM live balance:", balErr);
      }
    }

    return Response.json({
      publicKey: devWallet.public_key,
      network: devWallet.network,
      balance,
    });
  } catch (err: any) {
    console.error("[API] GET /api/developer/wallet error:", err);
    return Response.json({ error: err.message || "Failed to load developer wallet" }, { status: 500 });
  }
}

export async function POST(request: Request) {
  const ip = getClientIp(request);
  if (!apiLimiter.check(ip)) {
    return Response.json({ error: "Rate limited" }, { status: 429 });
  }

  const auth = await getAuth(request);
  if (!auth.isLoggedIn) {
    return Response.json({ error: "Unauthorized" }, { status: 401 });
  }

  try {
    const { action, privateKey: importedKey } = await request.json();
    const supabase = createAdminSupabase();
    
    // Fetch user record
    const { data: user } = await supabase
      .from("users")
      .select("id")
      .eq("wallet_address", auth.walletAddress)
      .single();

    if (!user) {
      return Response.json({ error: "User not found" }, { status: 404 });
    }

    const network = auth.walletKind === "solana" ? "solana" : "evm";

    if (action === "generate") {
      // Generate new wallet
      let publicKey = "";
      let secretKey = "";

      if (network === "solana") {
        const kp = Keypair.generate();
        publicKey = kp.publicKey.toBase58();
        secretKey = bs58.encode(kp.secretKey);
      } else {
        const wall = Wallet.createRandom();
        publicKey = wall.address;
        secretKey = wall.privateKey;
      }

      const { data: newWallet, error: upsertErr } = await supabase
        .from("developer_wallets")
        .upsert({
          user_id: user.id,
          wallet_address: auth.walletAddress,
          network,
          public_key: publicKey,
          encrypted_private_key: encrypt(secretKey),
          updated_at: new Date().toISOString(),
        }, {
          onConflict: "user_id,network"
        })
        .select()
        .single();

      if (upsertErr) throw new Error(upsertErr.message);

      return Response.json({
        success: true,
        publicKey: newWallet.public_key,
        network: newWallet.network,
        balance: 0,
      });
    }

    if (action === "import") {
      if (!importedKey || !importedKey.trim()) {
        return Response.json({ error: "Private key is required" }, { status: 400 });
      }

      let publicKey = "";
      let validatedKey = importedKey.trim();

      // Validate key
      try {
        if (network === "solana") {
          const keyBytes = bs58.decode(validatedKey);
          if (keyBytes.length !== 64) {
            throw new Error("Invalid Solana private key byte length");
          }
          const kp = Keypair.fromSecretKey(keyBytes);
          publicKey = kp.publicKey.toBase58();
        } else {
          const wall = new Wallet(validatedKey);
          publicKey = wall.address;
        }
      } catch (err) {
        return Response.json({ error: `Invalid private key format for ${network.toUpperCase()}` }, { status: 400 });
      }

      const { data: newWallet, error: upsertErr } = await supabase
        .from("developer_wallets")
        .upsert({
          user_id: user.id,
          wallet_address: auth.walletAddress,
          network,
          public_key: publicKey,
          encrypted_private_key: encrypt(validatedKey),
          updated_at: new Date().toISOString(),
        }, {
          onConflict: "user_id,network"
        })
        .select()
        .single();

      if (upsertErr) throw new Error(upsertErr.message);

      return Response.json({
        success: true,
        publicKey: newWallet.public_key,
        network: newWallet.network,
        balance: 0,
      });
    }

    if (action === "export") {
      // Fetch private key securely
      const { data: devWallet } = await supabase
        .from("developer_wallets")
        .select("encrypted_private_key")
        .eq("user_id", user.id)
        .eq("network", network)
        .single();

      if (!devWallet) {
        return Response.json({ error: "No wallet found to export" }, { status: 404 });
      }

      const decryptedKey = decrypt(devWallet.encrypted_private_key);
      return Response.json({ privateKey: decryptedKey });
    }

    return Response.json({ error: "Invalid action" }, { status: 400 });
  } catch (err: any) {
    console.error("[API] POST /api/developer/wallet error:", err);
    return Response.json({ error: err.message || "Failed to process wallet request" }, { status: 500 });
  }
}
