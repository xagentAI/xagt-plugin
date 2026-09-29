from __future__ import annotations
import secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from services.domain_verification import DomainVerifier
from services.candidate_service import CandidateNotFoundError, CandidateService, ProviderOwnershipConflictError
from services.identity_service import IdentityService
from services.marketplace_repository import MarketplaceRepository
from services.provider_verification import EndpointVerifier
from services.quote_service import QuoteService
from services.purchase_service import PurchaseService
from services.core_gateway import HttpCoreGateway
from services.registry_aggregation import RegistryAggregator
from adapters.cdp_bazaar import CdpBazaarAdapter
from adapters.clink_peer import ClinkPeerAdapter
from shared.ephemeral import EphemeralStore
from shared.config import AppConfig
from shared.manifest import ManifestClaim, canonicalize_manifest, manifest_hash
from shared.models import ClinkServiceManifest

WEB_ROOT=Path(__file__).resolve().parents[1]/"web"
CONSOLE_HEADERS={
    "Content-Security-Policy":"default-src 'self'; connect-src 'self'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
    "Referrer-Policy":"no-referrer",
    "X-Content-Type-Options":"nosniff",
    "X-Frame-Options":"DENY",
}

class SiweChallenge(BaseModel): address:str; domain:str
class SiweVerify(BaseModel): address:str; nonce:str; message:str; signature:str
class ClaimSubmit(BaseModel): claim:ManifestClaim; signature:str; wallet_address:str
class PreviewRequest(BaseModel):
    user_id:str;offering_id:str;service_input:dict;payment_index:int=0
    network:str|None=None;max_price_usd:str|None=None
    opc_installation_id:str|None=Field(default=None,pattern=r"^opc_[0-9a-f]{40}$")
class ExecuteRequest(BaseModel):
    user_confirmed:bool=False;spending_authorization_id:str|None=None
    transaction_hash:str|None=None;payment_response:dict|None=None
    opc_installation_id:str|None=Field(default=None,pattern=r"^opc_[0-9a-f]{40}$")
class ExternalCompleteRequest(BaseModel): transaction_hash:str; payment_response:dict
class ExternalCheckoutChallengeRequest(BaseModel): checkout_token:str; payer_address:str
class ExternalCheckoutCompleteRequest(BaseModel): checkout_token:str; payer_address:str; signature:str

def create_marketplace_app(config:AppConfig,repository:MarketplaceRepository,identity:IdentityService,core=None,endpoint_verifier=None):
    app=FastAPI(title="Clink Marketplace",version="1.0.0")
    app.mount("/assets",StaticFiles(directory=WEB_ROOT/"assets"),name="assets")
    @app.middleware("http")
    async def disable_admin_surface(request:Request,call_next):
        if config.admin_disabled and (
            request.url.path == "/admin" or request.url.path.startswith("/admin/")
        ):
            return JSONResponse(
                status_code=403,
                content={"detail":"admin operations are disabled"},
            )
        return await call_next(request)
    quotes=QuoteService(repository,native_provider_ids=config.native_provider_ids);candidates=CandidateService(repository); purchases=PurchaseService(repository,core,preview_ttl=config.purchase_preview_ttl_seconds,ephemeral_store=EphemeralStore(config.redis_url),native_provider_ids=config.native_provider_ids,registry_verified_max_price_usd=config.registry_verified_max_price_usd,public_base_url=config.public_base_url,eip3009_domains=config.eip3009_domains) if core else None
    domain_verifier=DomainVerifier();endpoint_verifier=endpoint_verifier or EndpointVerifier()
    adapters={"cdp_bazaar":CdpBazaarAdapter(search_url=config.bazaar_search_url,resources_url=config.bazaar_resources_url)}
    adapters.update({str(item.get("id") or f"peer_{index}"):ClinkPeerAdapter(str(item["url"])) for index,item in enumerate(config.peer_registries) if item.get("url")})
    aggregator=RegistryAggregator(
        repository,adapters,page_size=config.bazaar_sync_page_size,
        max_pages=config.bazaar_sync_max_pages,targeted_supply=config.bazaar_targets,
    )
    def merchant(token):
        address=repository.resolve_merchant_session(token or "")
        if not address: raise HTTPException(401,"merchant SIWE session required")
        return address
    def admin(token):
        if config.admin_disabled: raise HTTPException(403,"admin operations are disabled")
        address=merchant(token)
        if address.lower() not in config.admin_wallets: raise HTTPException(403,"admin wallet not allowed")
        return address
    def agent(token):
        supplied=(token or "").removeprefix("Bearer ")
        if not config.internal_api_token or supplied!=config.internal_api_token: raise HTTPException(401,"agent internal bearer token required")
    @app.get("/livez")
    def live():
        return {"service": "clink_marketplace", "status": "alive"}
    def readiness_status():
        worker = repository.worker_health(
            config.worker_heartbeat_timeout_seconds,
            stage_timeout_seconds=config.worker_stage_timeout_seconds,
            mandatory_stages=("registry_sync","offering_verify","domain_verify","purchase_finalization"),
        )
        registries = repository.registry_health(
            config.registry_freshness_timeout_seconds,
            expected_registry_ids=tuple(adapters),
        )
        try:
            core_health = core.health() if core and hasattr(core, "health") else {
                "status": "unavailable",
                "reason": "Core gateway is not configured",
            }
        except Exception as exc:
            core_health = {"status": "unavailable", "reason": str(exc)}
        ready = (
            worker["status"] == "ok"
            and all(item["status"] in {"succeeded","running"} for item in registries)
            and core_health.get("status") == "ok"
        )
        payload = {
            "service": "clink_marketplace",
            "status": "ok" if ready else "degraded",
            "mode": "trusted_agent_commerce",
            "api": {"status": "ok"},
            "worker": worker,
            "registries": registries,
            "core": core_health,
        }
        return payload,ready
    def operations_status():
        payload,ready=readiness_status()
        return {
            **payload,
            "metrics": repository.pilot_metrics(),
            "supply_targets": repository.bazaar_target_coverage(config.bazaar_targets),
        },ready
    @app.get("/healthz")
    def health():
        payload,ready=readiness_status()
        return payload if ready else JSONResponse(status_code=503,content=payload)
    @app.get("/merchant")
    def merchant_console():return FileResponse(WEB_ROOT/"merchant.html",headers=CONSOLE_HEADERS)
    @app.get("/admin")
    def admin_console():return FileResponse(WEB_ROOT/"admin.html",headers=CONSOLE_HEADERS)
    @app.get("/auth/siwe/config")
    def siwe_config():return {"allowed_domains":list(config.siwe_allowed_domains)}
    @app.post("/auth/siwe/challenge")
    def challenge(req:SiweChallenge):
        if req.domain.lower() not in config.siwe_allowed_domains: raise HTTPException(400,"SIWE domain not allowed")
        return identity.siwe_challenge(subject=req.address,domain=req.domain)
    @app.post("/auth/siwe/verify")
    def verify(req:SiweVerify):
        try: identity.consume_personal_signature(nonce=req.nonce,message=req.message,signature=req.signature,expected_address=req.address,allowed_domains=config.siwe_allowed_domains)
        except ValueError as exc: raise HTTPException(401,str(exc)) from exc
        token=secrets.token_urlsafe(32);repository.create_merchant_session(sha256(token.encode()).hexdigest(),req.address,datetime.now(UTC)+timedelta(hours=24));return {"access_token":token,"wallet_address":req.address.lower()}
    @app.get("/merchant/candidates")
    def list_candidates(domain:str|None=None,pay_to:str|None=None,query:str|None=None,limit:int=Query(20,ge=1,le=100),authorization:str|None=Header(None)):
        merchant((authorization or "").removeprefix("Bearer "))
        rows=candidates.list_candidates(domain=domain,pay_to=pay_to,query=query,limit=limit)
        return {"count":len(rows),"candidates":[{"provider":row["provider"].model_dump(mode="json"),"offering":row["offering"].model_dump(mode="json")} for row in rows]}
    @app.post("/merchant/candidates/{offering_id}/claim-draft")
    def claim_candidate_draft(offering_id:str,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "))
        try:manifest=candidates.create_manifest_draft(offering_id,wallet)
        except CandidateNotFoundError as exc:raise HTTPException(404,str(exc)) from exc
        except ProviderOwnershipConflictError as exc:raise HTTPException(409,str(exc)) from exc
        return {"manifest":manifest.model_dump(mode="json")}
    @app.post("/merchant/manifests")
    def submit_manifest(manifest:ClinkServiceManifest,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "))
        try:manifest=canonicalize_manifest(manifest)
        except ValueError as exc:raise HTTPException(400,str(exc)) from exc
        mid="manifest_"+secrets.token_hex(6)
        outcome,saved_manifest_id,status=repository.submit_manifest(mid,manifest,wallet)
        if outcome=="conflict": raise HTTPException(403,"manifest or provider owner mismatch")
        return {"manifest_id":saved_manifest_id,"manifest_hash":manifest_hash(manifest),"provider_id":manifest.provider.provider_id,"status":status}
    @app.get("/merchant/manifests")
    def list_manifests(authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "))
        rows=repository.list_merchant_manifests(wallet)
        return {"count":len(rows),"manifests":rows}
    @app.get("/merchant/providers")
    def merchant_providers(authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "))
        rows=repository.list_merchant_providers(wallet)
        return {"count":len(rows),"providers":rows}
    @app.get("/merchant/providers/{provider_id}/status")
    def merchant_provider_status(provider_id:str,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "))
        row=repository.merchant_provider_status(provider_id,wallet)
        if not row:raise HTTPException(404,"provider not found")
        return row
    @app.post("/merchant/manifests/{manifest_id}/claim-challenge")
    def claim_challenge(manifest_id:str,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "));manifest=repository.get_manifest(manifest_id,wallet)
        if not manifest: raise HTTPException(404,"manifest not found")
        challenge=identity.challenge(subject=wallet,purpose="manifest_claim")
        pay_to=[p.pay_to for o in manifest.offerings for p in o.payment_options]
        claim=ManifestClaim(manifest_hash=manifest_hash(manifest),domain=manifest.provider.domain,pay_to=pay_to,nonce=challenge["nonce"],issued_at=challenge["issued_at"],expires_at=challenge["expires_at"])
        return {"claim":claim,"typed_data":claim.typed_data()}
    @app.post("/merchant/manifests/{manifest_id}/submit-claim")
    def submit_claim(manifest_id:str,req:ClaimSubmit,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "));manifest=repository.get_manifest(manifest_id,wallet)
        if not manifest: raise HTTPException(404,"manifest not found")
        if req.claim.manifest_hash!=manifest_hash(manifest): raise HTTPException(400,"manifest hash mismatch")
        try: signer=identity.consume_manifest_claim(claim=req.claim,signature=req.signature,expected_address=wallet)
        except ValueError as exc: raise HTTPException(401,str(exc)) from exc
        if not repository.mark_manifest_wallet_verified(manifest_id,wallet,signer=signer,signature=req.signature): raise HTTPException(404,"manifest not found")
        return {"provider_id":manifest.provider.provider_id,"status":"wallet_verified"}
    @app.post("/merchant/providers/{provider_id}/verify-domain")
    def verify_domain(provider_id:str,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "));state,manifest_id,provider=repository.domain_verification_target(provider_id,wallet)
        if state=="manifest_required": raise HTTPException(403,"wallet-verified manifest required")
        if state=="invalid_manifest": raise HTTPException(409,"manifest canonical identity mismatch")
        if state=="conflict": raise HTTPException(409,"provider ownership conflict")
        try: domain_verifier.verify(domain=provider.domain,provider_id=provider_id,wallet_address=wallet)
        except Exception as exc: raise HTTPException(400,str(exc)) from exc
        state,status=repository.materialize_manifest_after_domain_verification(manifest_id,wallet)
        if state=="manifest_required": raise HTTPException(403,"wallet-verified manifest required")
        if state=="invalid_manifest": raise HTTPException(409,"manifest canonical identity mismatch")
        if state=="conflict": raise HTTPException(409,"provider ownership conflict")
        return {"provider_id":provider_id,"status":status}
    @app.post("/merchant/offerings/{offering_id}/verify")
    def verify_offering(offering_id:str,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "));snapshot=repository.get_offering_verification_snapshot(offering_id);offering=snapshot[0] if snapshot else None;provider=repository.get_provider(offering.provider_id) if offering else None
        if offering and not repository.is_provider_owner(offering.provider_id,wallet): raise HTTPException(403,"provider owner required")
        if not offering or not provider or provider.status not in {"domain_verified","active"}: raise HTTPException(409,"wallet and domain verification required")
        result=endpoint_verifier.verify(offering)
        completion=repository.complete_offering_verification(offering_id,result.verified,expected_payload_hash=snapshot[1])
        if not completion["applied"]:raise HTTPException(409,"offering verification result was not applied")
        return {
            "offering_id": offering_id,
            "status": completion["status"],
            "verification": result.model_dump(mode="json"),
        }
    @app.post("/merchant/offerings/{offering_id}/disable")
    def disable(offering_id:str,authorization:str|None=Header(None)):
        wallet=merchant((authorization or "").removeprefix("Bearer "));offering=repository.get_offering(offering_id)
        if not offering: raise HTTPException(404,"offering not found")
        if not repository.is_provider_owner(offering.provider_id,wallet): raise HTTPException(403,"provider owner required")
        repository.upsert_offering(offering.model_copy(update={"status":"disabled"}));return {"offering_id":offering_id,"status":"disabled"}
    @app.post("/admin/providers/{provider_id}/{operation}")
    def provider_admin(provider_id:str,operation:str,authorization:str|None=Header(None)):
        admin((authorization or "").removeprefix("Bearer "));provider=repository.get_provider(provider_id)
        if not provider or operation not in {"suspend","restore"}: raise HTTPException(404,"provider or operation not found")
        status=("suspended" if operation=="suspend" and repository.suspend_provider(provider_id) else repository.restore_provider(provider_id) if operation=="restore" else None)
        if not status:raise HTTPException(409,"provider state does not allow operation")
        return {"provider_id":provider_id,"status":status}
    @app.get("/admin/status")
    def admin_status(authorization:str|None=Header(None)):
        admin((authorization or "").removeprefix("Bearer "))
        return operations_status()[0]
    @app.get("/admin/providers")
    def admin_providers(query:str|None=None,status:str|None=None,limit:int=Query(100,ge=1,le=500),authorization:str|None=Header(None)):
        admin((authorization or "").removeprefix("Bearer "))
        rows=repository.list_admin_providers(query=query,status=status,limit=limit)
        return {"count":len(rows),"providers":rows}
    @app.post("/admin/registries/sync")
    def sync_registries(authorization:str|None=Header(None)):
        admin((authorization or "").removeprefix("Bearer "));return {"registries":aggregator.sync()}
    @app.get("/registry/export")
    def export_registry():
        rows=repository.search("",limit=100)
        return {"offerings":[{"provider":repository.get_provider(row.provider_id).model_dump(mode="json"),"offering":row.model_dump(mode="json"),"source_id":row.source_id} for row in rows],"next_cursor":None}
    @app.post("/catalog/search")
    def search(payload:dict):
        rows=repository.search(payload.get("query",""),payload.get("network"),payload.get("max_price_usd"),payload.get("limit",20));return {"count":len(rows),"offerings":[r.model_dump(mode="json") for r in rows]}
    @app.get("/catalog/offerings/{offering_id}")
    def offering_details(offering_id:str):
        offering=repository.active_offering(offering_id)
        if not offering: raise HTTPException(404,"verified offering not found")
        provider=repository.get_provider(offering.provider_id)
        return {"offering":offering.model_dump(mode="json"),"provider":provider.model_dump(mode="json") if provider else None,"reputation":repository.reputation(offering_id)}
    @app.post("/quotes/compare")
    def compare(payload:dict): return {"quotes":[q.model_dump(mode="json") for q in quotes.compare(payload.get("query",""),payload.get("network"),payload.get("max_price_usd"),payload.get("limit",10))]}
    @app.post("/purchases/previews")
    def preview(req:PreviewRequest,authorization:str|None=Header(None)):
        agent(authorization)
        if not purchases: raise HTTPException(503,"Core gateway not configured")
        try:
            payload=purchases.create_preview(**req.model_dump()).model_dump(mode="json")
            payload.pop("opc_installation_id",None)
            return payload
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    @app.post("/purchases/{preview_id}/execute")
    def execute(preview_id:str,req:ExecuteRequest,authorization:str|None=Header(None)):
        agent(authorization)
        if not purchases: raise HTTPException(503,"Core gateway not configured")
        try:return purchases.execute(preview_id,**req.model_dump())
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    @app.get("/purchases/previews/{preview_id}")
    def get_purchase_preview(preview_id:str,authorization:str|None=Header(None)):
        agent(authorization)
        row=repository.get_preview(preview_id)
        if not row: raise HTTPException(404,"preview not found")
        payload=row.model_dump(mode="json")
        payload.pop("opc_installation_id",None)
        return payload
    @app.get("/purchases/{purchase_id}")
    def get_purchase(purchase_id:str,authorization:str|None=Header(None)):
        agent(authorization)
        row=repository.get_purchase(purchase_id)
        if not row: raise HTTPException(404,"purchase not found")
        payload=row.model_dump(mode="json")
        payload["service_result"]=(
            purchases.result_for_purchase(purchase_id)
            if purchases and row.state=="delivered"
            else None
        )
        return payload
    @app.post("/purchases/{purchase_id}/external-complete")
    def external_complete(purchase_id:str,req:ExternalCompleteRequest,authorization:str|None=Header(None)):
        agent(authorization)
        if not purchases: raise HTTPException(503,"Core gateway not configured")
        try:return purchases.complete_external(purchase_id,**req.model_dump())
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    @app.get("/x402/checkout/{purchase_id}")
    def external_checkout_page(purchase_id:str):
        del purchase_id
        return FileResponse(WEB_ROOT/"x402_checkout.html",headers=CONSOLE_HEADERS)
    @app.post("/x402/checkout/{purchase_id}/challenge")
    def external_checkout_challenge(purchase_id:str,req:ExternalCheckoutChallengeRequest):
        if not purchases: raise HTTPException(503,"Core gateway not configured")
        try:return purchases.prepare_external_checkout(purchase_id,**req.model_dump())
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    @app.post("/x402/checkout/{purchase_id}/complete")
    def external_checkout_complete(purchase_id:str,req:ExternalCheckoutCompleteRequest):
        if not purchases: raise HTTPException(503,"Core gateway not configured")
        try:return purchases.complete_external_checkout(purchase_id,**req.model_dump())
        except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    return app

CONFIG=AppConfig.from_env()
REPOSITORY=MarketplaceRepository(CONFIG.database_url)
CORE=(HttpCoreGateway(action_url=CONFIG.core_action_url,policy_url=CONFIG.core_policy_url,audit_url=CONFIG.core_audit_url,funding_url=CONFIG.core_funding_url,account_url=CONFIG.core_account_url,token=CONFIG.core_internal_api_token,health_timeout_seconds=CONFIG.core_health_timeout_seconds,health_deadline_seconds=CONFIG.core_health_deadline_seconds) if CONFIG.core_internal_api_token else None)
app=create_marketplace_app(CONFIG,REPOSITORY,IdentityService(REPOSITORY),CORE)

if __name__=="__main__":
    import uvicorn
    uvicorn.run(app,host=CONFIG.registry_host,port=CONFIG.registry_port)
