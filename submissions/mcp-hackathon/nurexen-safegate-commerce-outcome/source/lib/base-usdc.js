"use strict";

const BASE_CHAIN_ID = 8453;
const BASE_CHAIN_HEX = "0x2105";
const BASE_USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913";
const TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const DEFAULT_RPC = "https://mainnet.base.org";

function normalizedAddress(value) {
  const address = String(value || "").trim().toLowerCase();
  if (!/^0x[a-f0-9]{40}$/.test(address)) throw Object.assign(new Error("Invalid EVM address."), { code: "INVALID_EVM_ADDRESS" });
  return address;
}

function topicAddress(topic) {
  const value = String(topic || "").toLowerCase();
  if (!/^0x[a-f0-9]{64}$/.test(value)) return null;
  return "0x" + value.slice(-40);
}

function rpcError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

async function rpcCall(method, params, options = {}) {
  const rpcUrl = String(options.rpcUrl || process.env.BASE_RPC_URL || DEFAULT_RPC);
  const timeoutMs = Number(options.timeoutMs || 12000);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(rpcUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
      signal: controller.signal
    });

    if (!response.ok) throw rpcError("BASE_RPC_HTTP_ERROR", "Base RPC returned HTTP " + response.status);

    const payload = await response.json();
    if (payload && payload.error) throw rpcError("BASE_RPC_ERROR", String(payload.error.message || "Base RPC error"));
    return payload ? payload.result : null;
  } catch (error) {
    if (error && error.name === "AbortError") throw rpcError("BASE_RPC_TIMEOUT", "Base RPC request timed out.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function verifyReceiptTransfer(receipt, expected) {
  if (!receipt) throw rpcError("TRANSACTION_NOT_FOUND", "Transaction receipt was not found.");
  if (String(receipt.status || "").toLowerCase() !== "0x1") throw rpcError("TRANSACTION_FAILED", "Transaction did not succeed on-chain.");

  const sender = normalizedAddress(expected.paymentSender);
  const receiver = normalizedAddress(expected.merchantReceiver);
  const amount = BigInt(String(expected.amountBaseUnits || "0"));

  if (amount <= 0n) throw rpcError("INVALID_AMOUNT", "Expected USDC amount must be positive.");

  const logs = Array.isArray(receipt.logs) ? receipt.logs : [];

  const matchingLog = logs.find(log => {
    if (String(log.address || "").toLowerCase() !== BASE_USDC) return false;
    const topics = Array.isArray(log.topics) ? log.topics : [];
    if (String(topics[0] || "").toLowerCase() !== TRANSFER_TOPIC) return false;
    if (topicAddress(topics[1]) !== sender) return false;
    if (topicAddress(topics[2]) !== receiver) return false;

    try {
      return BigInt(String(log.data || "0x0")) === amount;
    } catch (_) {
      return false;
    }
  });

  if (!matchingLog) {
    throw rpcError("USDC_TRANSFER_MISMATCH", "No matching Base USDC transfer was found for sender, receiver and exact amount.");
  }

  return {
    payment_status: "PAYMENT_VERIFIED",
    chain_id: BASE_CHAIN_ID,
    asset: "USDC",
    token_contract: BASE_USDC,
    transaction_hash: String(receipt.transactionHash || expected.transactionHash || "").toLowerCase(),
    block_number: parseInt(String(receipt.blockNumber || "0x0"), 16),
    payment_sender: sender,
    merchant_receiver: receiver,
    amount_base_units: amount.toString()
  };
}

async function verifyBaseUsdcTransfer(expected, options = {}) {
  const txHash = String(expected.transactionHash || "").trim().toLowerCase();
  if (!/^0x[a-f0-9]{64}$/.test(txHash)) throw rpcError("INVALID_TRANSACTION_HASH", "A valid transaction hash is required.");

  const chainId = await rpcCall("eth_chainId", [], options);
  if (String(chainId || "").toLowerCase() !== BASE_CHAIN_HEX) {
    throw rpcError("UNEXPECTED_RPC_CHAIN", "Configured RPC is not Base Mainnet.");
  }

  const receipt = await rpcCall("eth_getTransactionReceipt", [txHash], options);
  return verifyReceiptTransfer(receipt, { ...expected, transactionHash: txHash });
}

module.exports = {
  BASE_CHAIN_ID,
  BASE_USDC,
  TRANSFER_TOPIC,
  verifyReceiptTransfer,
  verifyBaseUsdcTransfer
};
