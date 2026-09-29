from __future__ import annotations
import base64,hashlib,hmac,json

def verify_clink_receipt(token:str,*,secret:str,merchant_id:str,resource:str)->dict:
    padding="="*(-len(token)%4);receipt=json.loads(base64.urlsafe_b64decode(token+padding))
    metadata=receipt.get("metadata",{});scope=metadata.get("receipt_scope",{});signature=metadata.get("receipt_signature","")
    expected="sha256="+hmac.new(secret.encode(),json.dumps(scope,sort_keys=True,separators=(",",":")).encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature,expected):raise ValueError("invalid Clink receipt signature")
    if scope.get("merchant_id")!=merchant_id or scope.get("resource")!=resource or scope.get("receipt_id")!=receipt.get("receipt_id"):
        raise ValueError("Clink receipt scope mismatch")
    return receipt
