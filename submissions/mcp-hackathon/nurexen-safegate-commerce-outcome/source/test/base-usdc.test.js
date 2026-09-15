"use strict";
const assert = require("assert");
const { BASE_USDC, TRANSFER_TOPIC, verifyReceiptTransfer } = require("../lib/base-usdc");

function topic(address) {
  return "0x" + "0".repeat(24) + address.toLowerCase().replace(/^0x/, "");
}

const sender = "0x" + "1".repeat(40);
const receiver = "0x" + "2".repeat(40);
const txHash = "0x" + "a".repeat(64);

const receipt = {
  status: "0x1",
  transactionHash: txHash,
  blockNumber: "0x1234",
  logs: [{
    address: BASE_USDC,
    topics: [TRANSFER_TOPIC, topic(sender), topic(receiver)],
    data: "0x186a0"
  }]
};

const verified = verifyReceiptTransfer(receipt, {
  transactionHash: txHash,
  paymentSender: sender,
  merchantReceiver: receiver,
  amountBaseUnits: "100000"
});

assert.strictEqual(verified.payment_status, "PAYMENT_VERIFIED");
assert.strictEqual(verified.amount_base_units, "100000");
assert.strictEqual(verified.chain_id, 8453);

assert.throws(
  () => verifyReceiptTransfer(receipt, {
    transactionHash: txHash,
    paymentSender: sender,
    merchantReceiver: receiver,
    amountBaseUnits: "100001"
  }),
  error => error && error.code === "USDC_TRANSFER_MISMATCH"
);

console.log("BASE_USDC_RECEIPT_TEST=PASS");
