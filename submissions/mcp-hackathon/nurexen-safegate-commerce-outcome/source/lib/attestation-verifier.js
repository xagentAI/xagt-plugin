"use strict";

const crypto=require("crypto");
const fs=require("fs");
const path=require("path");
const {canonicalJson}=require("./canonical-json");

const PUBLIC_KEY_PATH=path.join(__dirname,"..","verification","public-key.txt");

function fail(code,message){
  const error=new Error(message||code);
  error.code=code;
  throw error;
}

function requirePattern(value,pattern,code){
  const text=String(value||"").trim();
  if(!pattern.test(text))fail(code,"Invalid attestation field.");
  return text;
}

function validatePayload(payload){
  if(!payload||typeof payload!=="object"||Array.isArray(payload))fail("INVALID_ATTESTATION_PAYLOAD");

  if(payload.schema!=="SAFEGATE_COMMERCE_ATTESTATION_V1")fail("UNSUPPORTED_ATTESTATION_SCHEMA");

  requirePattern(payload.requestId,/^SG-EVM-REQ-[A-Z0-9-]{12,80}$/,"INVALID_REQUEST_ID");
  requirePattern(payload.orderReference,/^SG-ORDER-[A-F0-9]{20}$/,"INVALID_ORDER_REFERENCE");
  const txRef=requirePattern(payload.transactionReference,/^SG-TX-[A-F0-9]{24}$/,"INVALID_TRANSACTION_REFERENCE");
  requirePattern(payload.transactionHash,/^0x[a-fA-F0-9]{64}$/,"INVALID_TRANSACTION_HASH");
  requirePattern(payload.paymentSender,/^0x[a-fA-F0-9]{40}$/,"INVALID_PAYMENT_SENDER");
  requirePattern(payload.merchantReceiver,/^0x[a-fA-F0-9]{40}$/,"INVALID_MERCHANT_RECEIVER");
  requirePattern(payload.amountBaseUnits,/^[1-9][0-9]*$/,"INVALID_AMOUNT");

  if(Number(payload.chainId)!==8453)fail("UNSUPPORTED_CHAIN");
  if(String(payload.asset||"").toUpperCase()!=="USDC")fail("UNSUPPORTED_ASSET");
  if(String(payload.fulfillmentStatus||"").toUpperCase()!=="FULFILLMENT_COMPLETED")fail("FULFILLMENT_NOT_COMPLETED");
  if(String(payload.evidenceStatus||"").toUpperCase()!=="EVIDENCE_CREATED")fail("EVIDENCE_NOT_CREATED");

  if(String(payload.receiptReference||"")!==txRef+"-RCPT")fail("RECEIPT_BINDING_MISMATCH");
  if(String(payload.evidenceReference||"")!==txRef+"-EVID")fail("EVIDENCE_BINDING_MISMATCH");
  if(String(payload.proofReference||"")!==txRef+"-PROOF")fail("PROOF_BINDING_MISMATCH");

  if(String(payload.paymentSender).toLowerCase()===String(payload.merchantReceiver).toLowerCase()){
    fail("BUYER_AND_MERCHANT_WALLET_MUST_DIFFER");
  }

  return payload;
}

function verifyCommerceAttestation(attestation){
  if(!attestation||typeof attestation!=="object")fail("INVALID_ATTESTATION");

  const payload=validatePayload(attestation.payload);
  const signature=String(attestation.signature||"").trim();

  if(!/^[A-Za-z0-9_-]{80,120}$/.test(signature))fail("INVALID_ATTESTATION_SIGNATURE_FORMAT");

  const publicKey=crypto.createPublicKey(fs.readFileSync(PUBLIC_KEY_PATH));
  const valid=crypto.verify(
    null,
    Buffer.from(canonicalJson(payload),"utf8"),
    publicKey,
    Buffer.from(signature,"base64url")
  );

  if(!valid)fail("ATTESTATION_SIGNATURE_INVALID");

  return {
    ok:true,
    attestation_status:"VALID",
    issuer:"SAFEGATE",
    schema:payload.schema,
    transaction_reference:payload.transactionReference,
    proof_reference:payload.proofReference
  };
}

module.exports={verifyCommerceAttestation,validatePayload};
