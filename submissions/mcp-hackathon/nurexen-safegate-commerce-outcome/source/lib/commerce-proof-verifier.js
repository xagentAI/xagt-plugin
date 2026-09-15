"use strict";

const {verifyCommerceAttestation}=require("./attestation-verifier");
const {verifyBaseUsdcTransfer}=require("./base-usdc");

function fail(code,message){
  const error=new Error(message||code);
  error.code=code;
  throw error;
}

async function verifyCommerceProof(attestation,options={}){
  const attestationResult=verifyCommerceAttestation(attestation);
  const payload=attestation.payload;

  const payment=await verifyBaseUsdcTransfer({
    transactionHash:payload.transactionHash,
    paymentSender:payload.paymentSender,
    merchantReceiver:payload.merchantReceiver,
    amountBaseUnits:payload.amountBaseUnits
  },options);

  if(payment.transaction_hash!==String(payload.transactionHash).toLowerCase())
    fail("TRANSACTION_BINDING_MISMATCH");

  if(payment.payment_sender!==String(payload.paymentSender).toLowerCase())
    fail("PAYMENT_SENDER_BINDING_MISMATCH");

  if(payment.merchant_receiver!==String(payload.merchantReceiver).toLowerCase())
    fail("MERCHANT_RECEIVER_BINDING_MISMATCH");

  if(payment.amount_base_units!==String(payload.amountBaseUnits))
    fail("PAYMENT_AMOUNT_BINDING_MISMATCH");

  if(payment.chain_id!==Number(payload.chainId))
    fail("CHAIN_BINDING_MISMATCH");

  if(payment.asset!==String(payload.asset).toUpperCase())
    fail("ASSET_BINDING_MISMATCH");

  return {
    ok:true,
    capability:"safegate_commerce_outcome",
    version:"0.3.0",
    outcome:"COMMERCE_VERIFIED",
    side_effects:"none",

    payment_status:payment.payment_status,
    attestation_status:attestationResult.attestation_status,
    fulfillment_status:String(payload.fulfillmentStatus).toUpperCase(),
    evidence_status:String(payload.evidenceStatus).toUpperCase(),

    request_id:payload.requestId,
    order_reference:payload.orderReference,
    safegate_transaction:payload.transactionReference,
    transaction_hash:payment.transaction_hash,

    chain_id:payment.chain_id,
    asset:payment.asset,
    amount_base_units:payment.amount_base_units,
    payment_sender:payment.payment_sender,
    merchant_receiver:payment.merchant_receiver,

    receipt_reference:payload.receiptReference,
    evidence_reference:payload.evidenceReference,
    proof_reference:payload.proofReference,

    payment_verification:{
      source:"BASE_MAINNET_RPC",
      token_contract:payment.token_contract,
      block_number:payment.block_number
    },

    attestation_verification:{
      issuer:"SAFEGATE",
      scheme:"Ed25519",
      schema:payload.schema
    }
  };
}

module.exports={verifyCommerceProof};
