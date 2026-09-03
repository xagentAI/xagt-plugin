"use strict";
const assert = require("assert");
const { evaluateCommerceOutcome } = require("../lib/commerce-outcome");

const base = {
  requestId: "SG-EVM-REQ-TEST123456789ABC",
  orderReference: "SG-ORDER-1234567890ABCDEF",
  transactionHash: "0x" + "a".repeat(64),
  safeGateTransaction: "SG-TX-1234567890ABCDEF",
  evidenceReference: "SG-TX-1234567890ABCDEF-EVID",
  proofReference: "SG-TX-1234567890ABCDEF-PROOF",
  paymentSender: "0x" + "1".repeat(40),
  merchantReceiver: "0x" + "2".repeat(40),
  amountBaseUnits: "100000",
  chainId: 8453,
  asset: "USDC",
  paymentStatus: "PAYMENT_VERIFIED",
  fulfillmentStatus: "FULFILLMENT_COMPLETED",
  evidenceStatus: "EVIDENCE_CREATED"
};

const complete = evaluateCommerceOutcome(base);
assert.strictEqual(complete.outcome, "COMMERCE_VERIFIED");
assert.strictEqual(complete.request_binding, "VALID");

const pending = evaluateCommerceOutcome({
  ...base,
  fulfillmentStatus: "PENDING_MERCHANT_ACTION",
  evidenceStatus: "EVIDENCE_CREATED"
});
assert.strictEqual(pending.outcome, "PAYMENT_VERIFIED_FULFILLMENT_PENDING");

assert.throws(
  () => evaluateCommerceOutcome({ ...base, proofReference: "SG-TX-1234567890ABCDEF-EVID" }),
  error => error && error.code === "INVALID_PROOF_REFERENCE"
);

console.log("COMMERCE_OUTCOME_CONTRACT_TEST=PASS");
