"use strict";

function fail(code, message) {
  const error = new Error(message);
  error.code = code;
  throw error;
}

function requireString(value, code, pattern) {
  const normalized = String(value || "").trim();
  if (!normalized || (pattern && !pattern.test(normalized))) {
    fail(code, "Invalid or missing field.");
  }
  return normalized;
}

function evaluateCommerceOutcome(input) {
  if (!input || typeof input !== "object" || Array.isArray(input)) {
    fail("INVALID_INPUT", "A JSON object is required.");
  }

  const requestId = requireString(input.requestId, "INVALID_REQUEST_ID", /^SG-EVM-REQ-[A-Z0-9-]{12,80}$/);
  const orderReference = requireString(input.orderReference, "INVALID_ORDER_REFERENCE", /^SG-ORDER-[A-Z0-9]{16,40}$/);
  const transactionHash = requireString(input.transactionHash, "INVALID_TRANSACTION_HASH", /^0x[a-fA-F0-9]{64}$/).toLowerCase();
  const safeGateTransaction = requireString(input.safeGateTransaction, "INVALID_SAFEGATE_TRANSACTION", /^SG-TX-[A-Z0-9]{16,40}$/);
  const evidenceReference = requireString(input.evidenceReference, "INVALID_EVIDENCE_REFERENCE", /^SG-TX-[A-Z0-9]{16,40}-EVID$/);
  const proofReference = requireString(input.proofReference, "INVALID_PROOF_REFERENCE", /^SG-TX-[A-Z0-9]{16,40}-PROOF$/);
  const paymentSender = requireString(input.paymentSender, "INVALID_PAYMENT_SENDER", /^0x[a-fA-F0-9]{40}$/).toLowerCase();
  const merchantReceiver = requireString(input.merchantReceiver, "INVALID_MERCHANT_RECEIVER", /^0x[a-fA-F0-9]{40}$/).toLowerCase();
  const amountBaseUnits = requireString(input.amountBaseUnits, "INVALID_AMOUNT", /^[1-9][0-9]*$/);

  if (Number(input.chainId) !== 8453) fail("UNSUPPORTED_CHAIN", "Base Mainnet chain ID 8453 is required.");
  if (String(input.asset || "").toUpperCase() !== "USDC") fail("UNSUPPORTED_ASSET", "USDC is required.");
  if (paymentSender === merchantReceiver) fail("BUYER_AND_MERCHANT_WALLET_MUST_DIFFER", "Buyer and merchant wallets must differ.");

  if (evidenceReference !== safeGateTransaction + "-EVID") {
    fail("EVIDENCE_BINDING_MISMATCH", "Evidence reference is not bound to the SafeGate transaction.");
  }

  if (proofReference !== safeGateTransaction + "-PROOF") {
    fail("PROOF_BINDING_MISMATCH", "Proof reference is not bound to the SafeGate transaction.");
  }

  const paymentStatus = String(input.paymentStatus || "").toUpperCase();
  const fulfillmentStatus = String(input.fulfillmentStatus || "").toUpperCase();
  const evidenceStatus = String(input.evidenceStatus || "").toUpperCase();

  if (paymentStatus !== "PAYMENT_VERIFIED") {
    fail("PAYMENT_NOT_VERIFIED", "Payment must be verified before a commerce outcome can be confirmed.");
  }

  let outcome = "PAYMENT_VERIFIED_FULFILLMENT_PENDING";

  if (fulfillmentStatus === "FULFILLMENT_COMPLETED") {
    if (evidenceStatus !== "EVIDENCE_CREATED") {
      fail("EVIDENCE_REQUIRED", "Completed fulfillment requires created evidence.");
    }
    outcome = "COMMERCE_VERIFIED";
  } else if (fulfillmentStatus !== "PENDING_MERCHANT_ACTION") {
    fail("INVALID_FULFILLMENT_STATUS", "Unsupported fulfillment status.");
  }

  return {
    ok: true,
    capability: "safegate_commerce_outcome",
    version: "0.1.0",
    side_effects: "none",
    verification_scope: "REFERENCE_AND_COMMERCE_STATE_CONSISTENCY",
    outcome,
    payment_status: paymentStatus,
    request_binding: "VALID",
    fulfillment_status: fulfillmentStatus,
    evidence_status: evidenceStatus,
    evidence_reference: evidenceReference,
    proof_reference: proofReference,
    request_id: requestId,
    order_reference: orderReference,
    safegate_transaction: safeGateTransaction,
    transaction_hash: transactionHash,
    chain_id: 8453,
    asset: "USDC",
    amount_base_units: amountBaseUnits,
    payment_sender: paymentSender,
    merchant_receiver: merchantReceiver
  };
}

module.exports = { evaluateCommerceOutcome };
