"use strict";

const {verifyCommerceProof}=require("../lib/commerce-proof-verifier");

module.exports=async function handler(req,res){
  if(req.method==="GET"){
    return res.status(200).json({
      ok:true,
      capability:"safegate_commerce_outcome",
      version:"0.3.0",
      method:"POST",
      side_effects:"none",
      verifies:[
        "SafeGate Ed25519 commerce attestation",
        "Base Mainnet USDC payment"
      ]
    });
  }

  if(req.method!=="POST"){
    res.setHeader("Allow","GET, POST");
    return res.status(405).json({ok:false,error:{code:"METHOD_NOT_ALLOWED"}});
  }

  try{
    const attestation=req.body?.attestation||req.body;
    const result=await verifyCommerceProof(attestation);
    return res.status(200).json(result);
  }catch(error){
    const code=String(error.code||"VERIFICATION_FAILED");
    const upstream=[
      "BASE_RPC_TIMEOUT",
      "BASE_RPC_HTTP_ERROR",
      "BASE_RPC_ERROR"
    ].includes(code);

    return res.status(upstream?502:400).json({
      ok:false,
      error:{
        code,
        message:String(error.message||"Commerce verification failed.")
      }
    });
  }
};
