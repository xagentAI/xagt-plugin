from __future__ import annotations
import secrets
from datetime import UTC, datetime, timedelta
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from services.marketplace_repository import MarketplaceRepository
from shared.manifest import ManifestClaim

class IdentityService:
    def __init__(self, repository: MarketplaceRepository): self.repository=repository
    def challenge(self, *, subject, purpose, payload=None, ttl=300):
        nonce=secrets.token_urlsafe(24);now=datetime.now(UTC)
        item={"nonce":nonce,"subject":subject,"purpose":purpose,"payload":payload or {},"issued_at":now,"expires_at":now+timedelta(seconds=ttl),"consumed":False}
        self.repository.save_challenge(item)
        return item
    def siwe_challenge(self, *, subject, domain, ttl=300):
        nonce=secrets.token_urlsafe(24);now=datetime.now(UTC);address=subject.lower();normalized_domain=domain.lower()
        message=f"{normalized_domain} wants you to sign in with your Ethereum account:\n{subject}\n\nNonce: {nonce}"
        item={"nonce":nonce,"subject":address,"purpose":"siwe","payload":{"address":address,"domain":normalized_domain,"nonce":nonce,"message":message},"issued_at":now,"expires_at":now+timedelta(seconds=ttl),"consumed":False,"message":message}
        self.repository.save_challenge(item)
        return item
    def consume_personal_signature(self, *, nonce, message, signature, expected_address, allowed_domains):
        challenge=self.repository.get_challenge(nonce,"siwe",expected_address)
        if not challenge:raise ValueError("challenge missing or already consumed")
        payload=challenge["payload"]
        domain=str(payload.get("domain") or "").lower();address=str(payload.get("address") or "").lower()
        if domain not in {item.lower() for item in allowed_domains}:raise ValueError("SIWE domain not allowed")
        if address!=expected_address.lower() or payload.get("nonce")!=nonce:raise ValueError("SIWE challenge mismatch")
        if payload.get("message")!=message or f"Nonce: {nonce}" not in message:raise ValueError("SIWE message mismatch")
        try:recovered=Account.recover_message(encode_defunct(text=message),signature=signature)
        except Exception as exc:raise ValueError("invalid personal signature") from exc
        if recovered.lower()!=expected_address.lower(): raise ValueError("signature signer mismatch")
        self._consume(nonce,"siwe",expected_address)
        return recovered
    def consume_manifest_claim(self, *, claim:ManifestClaim, signature, expected_address):
        self._consume(claim.nonce,"manifest_claim",expected_address);claim.assert_fresh()
        recovered=Account.recover_message(encode_typed_data(full_message=claim.typed_data()),signature=signature)
        if recovered.lower()!=expected_address.lower(): raise ValueError("manifest signer mismatch")
        return recovered
    def _consume(self,nonce,purpose,subject):
        if not self.repository.consume_challenge(nonce,purpose,subject): raise ValueError("challenge missing or already consumed")
