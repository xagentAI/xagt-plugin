from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from eth_account import Account
from eth_account.messages import encode_typed_data

from services.identity_service import IdentityService
from services.marketplace_repository import MarketplaceRepository
from services.purchase_service import PurchaseService
from shared.manifest import ManifestClaim
from shared.models import PaymentOption, Provider, ServiceOffering

USDC = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
SPENDER = "0x" + "4" * 40

class Core:
    def __init__(self,approved=True):self.approved=approved;self.reserves=0
    def create_action(self,p):return {"action_id":"action_1"}
    def evaluate_policy(self,p):return {"policy_decision_id":"policy_1","approved":self.approved}
    def update_action(self,*a,**k):return {}
    def audit(self,p):return {"event_id":"audit_1"}
    def funding_readiness(self):return {"spender_address":SPENDER}
    def resolve_authorization(self,p):
        result={"ready":True,"authorization_rail":p["authorization_rail"],"wallet_identity_id":"wallet_1","spending_grant_id":"grant_1"}
        if p["authorization_rail"]=="native_allowance":result["asset_allowance_id"]="allowance_1"
        return result
    def reserve(self,p):self.reserves+=1;return {"reservation_id":"reserve_1","nonce":"0x"+"9"*64,"valid_after":"100","valid_before":"200"}
    def settle(self,r,p):return {"state":"settled","receipt_id":"receipt_1","tx_hash":"0xabc"}
    def finalize(self,r,p):return {"state":"finalized"}

class Response:
    is_success=True;headers={"content-type":"application/json"}
    def json(self):return {"risk":"low"}
class Client:
    def request(self,*a,**kw):return Response()

def repository(directory, *, native=True):
    repo=MarketplaceRepository(f"sqlite+pysqlite:///{Path(directory)/'market.db'}")
    provider=Provider(name="Risk",domain="risk.example",source="merchant",status="active")
    offering=ServiceOffering(provider_id=provider.provider_id,source="merchant",source_id="POST https://risk.example/check",name="Risk",endpoint="https://risk.example/check",method="POST",status="verified",metadata={"accepts_clink_receipt":native},payment_options=[PaymentOption(scheme="exact",network="eip155:137",asset=USDC,amount_atomic="10000",pay_to="0x"+"3"*40,price_usd="0.01")])
    repo.upsert_provider(provider);repo.upsert_offering(offering,verified_at=datetime.now(UTC));return repo,offering

def test_native_purchase_is_idempotent_and_stores_only_hashes():
    with TemporaryDirectory() as directory:
        repo,offering=repository(directory);core=Core();service=PurchaseService(repo,core,client=Client(),native_provider_ids={offering.provider_id})
        preview=service.create_preview(user_id="u",offering_id=offering.offering_id,service_input={"secret":"never persist"})
        result=service.execute(preview.preview_id,user_confirmed=True,spending_authorization_id="auth")
        replay=service.execute(preview.preview_id,user_confirmed=True,spending_authorization_id="auth")
        assert result.state=="delivered" and replay.purchase_id==result.purchase_id and core.reserves==1
        assert "never persist" not in str(repo.get_purchase(result.purchase_id).model_dump())

def test_external_x402_requires_per_purchase_signature():
    with TemporaryDirectory() as directory:
        repo,offering=repository(directory,native=False);service=PurchaseService(repo,Core())
        preview=service.create_preview(user_id="u",offering_id=offering.offering_id,service_input={"x":1})
        assert service.execute(preview.preview_id,user_confirmed=True,spending_authorization_id="auth").state=="signing_required"

def test_manifest_claim_recovers_wallet_and_rejects_replay():
    with TemporaryDirectory() as directory:
        identity=IdentityService(MarketplaceRepository(f"sqlite+pysqlite:///{Path(directory)/'market.db'}"));account=Account.create();challenge=identity.challenge(subject=account.address,purpose="manifest_claim")
        claim=ManifestClaim(manifest_hash="0x"+"1"*64,domain="risk.example",pay_to=["0x"+"2"*40],nonce=challenge["nonce"],issued_at=challenge["issued_at"],expires_at=challenge["expires_at"])
        signature=Account.sign_message(encode_typed_data(full_message=claim.typed_data()),account.key).signature.hex()
        assert identity.consume_manifest_claim(claim=claim,signature=signature,expected_address=account.address)==account.address
        try: identity.consume_manifest_claim(claim=claim,signature=signature,expected_address=account.address)
        except ValueError as exc: assert "already consumed" in str(exc)
        else: raise AssertionError("replay accepted")

def test_finalization_outbox_uses_fenced_claims():
    with TemporaryDirectory() as directory:
        repo,offering=repository(directory);core=Core();service=PurchaseService(repo,core,client=Client(),native_provider_ids={offering.provider_id})
        preview=service.create_preview(user_id="u",offering_id=offering.offering_id,service_input={"x":1})
        core.finalize=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("Core unavailable"))
        result=service.execute(preview.preview_id,user_confirmed=True,spending_authorization_id="auth")
        items=repo.claim_finalizations("worker-a")
        assert result.state=="delivered" and len(items)==1
        assert repo.finish_finalization(items[0]["outbox_id"],"worker-b") is False
        assert repo.finish_finalization(items[0]["outbox_id"],items[0]["claim_token"],"retry") is True
