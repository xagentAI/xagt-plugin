const purchaseId=location.pathname.split("/").filter(Boolean).at(-1);
const token=new URLSearchParams(location.hash.slice(1)).get("token");
const pay=document.querySelector("#pay");
const status=document.querySelector("#status");
document.querySelector("#purchase").textContent=purchaseId||"Invalid purchase";

function setStatus(message,error=false){status.textContent=message;status.style.color=error?"#ff826f":"#48f59a"}
function short(value){return value?value.slice(0,8)+"…"+value.slice(-6):"—"}
async function post(path,body){
  const response=await fetch(path,{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify(body)});
  const payload=await response.json();
  if(!response.ok)throw new Error(payload.detail||"Checkout request failed");
  return payload;
}
pay.addEventListener("click",async()=>{
  if(!token){setStatus("This checkout link is missing its one-time token.",true);return}
  if(!window.ethereum){setStatus("Open this link in a browser with an EVM wallet.",true);return}
  pay.disabled=true;
  try{
    setStatus("Connecting wallet…");
    const [payer]=await window.ethereum.request({method:"eth_requestAccounts"});
    const challenge=await post(`/x402/checkout/${purchaseId}/challenge`,{checkout_token:token,payer_address:payer});
    const payment=challenge.payment;
    document.querySelector("#amount").textContent=`${Number(payment.amount)/1e6} USDC`;
    document.querySelector("#network").textContent=payment.network;
    document.querySelector("#recipient").textContent=short(payment.payTo);
    const chainId="0x"+Number(challenge.typed_data.domain.chainId).toString(16);
    try{await window.ethereum.request({method:"wallet_switchEthereumChain",params:[{chainId}]})}
    catch(error){if(error.code!==4902)throw error}
    setStatus("Confirm the exact x402 authorization in your wallet…");
    const signature=await window.ethereum.request({method:"eth_signTypedData_v4",params:[payer,JSON.stringify(challenge.typed_data)]});
    setStatus("Payment signed. Waiting for merchant settlement…");
    const result=await post(`/x402/checkout/${purchaseId}/complete`,{checkout_token:token,payer_address:payer,signature});
    const purchase=result.purchase||result;
    if(purchase.state!=="delivered")throw new Error(`Payment state: ${purchase.state}`);
    setStatus("Paid and delivered. You can return to Agentonomy.");
    pay.textContent="Purchase complete";
  }catch(error){
    setStatus(error.message||"Checkout failed",true);
    pay.disabled=false;
  }
});
