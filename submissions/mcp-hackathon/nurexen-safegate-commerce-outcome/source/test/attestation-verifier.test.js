"use strict";
const assert=require("assert");
const fs=require("fs");
const path=require("path");
const {verifyCommerceAttestation}=require("../lib/attestation-verifier");

const sample=JSON.parse(
  fs.readFileSync(
    path.join(__dirname,"..","verification","sample-synthetic-attestation.json"),
    "utf8"
  )
);

const valid=verifyCommerceAttestation(sample);
assert.strictEqual(valid.ok,true);
assert.strictEqual(valid.attestation_status,"VALID");

const tampered=JSON.parse(JSON.stringify(sample));
tampered.payload.amountBaseUnits="100001";

assert.throws(
  ()=>verifyCommerceAttestation(tampered),
  error=>error&&error.code==="ATTESTATION_SIGNATURE_INVALID"
);

console.log("ATTESTATION_VERIFIER_TEST=PASS");
console.log("TAMPER_DETECTION_TEST=PASS");
