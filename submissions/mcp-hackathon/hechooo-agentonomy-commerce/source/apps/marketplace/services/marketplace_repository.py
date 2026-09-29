from __future__ import annotations
import json, secrets
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import String, cast, create_engine, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from shared.commerce import Purchase, PurchasePreview, eligible_payment_options
from shared.manifest import canonicalize_manifest, manifest_hash, normalize_provider_domain
from shared.models import ClinkServiceManifest, Provider, ServiceOffering
from shared.security import payment_recipient_matches
from services.reputation_service import (
    WEIGHTS,
    aggregate_reputation_events,
    validate_reputation_event,
)
from storage.tables import Base, ChallengeRow, ManifestRow, MerchantSessionRow, OfferingRow, ProviderRow, ProvenanceRow, PurchaseFinalizationRow, PurchasePreviewRow, PurchaseRow, RegistryCursorRow, ReputationEventRow, ReputationRow, WorkerHeartbeatRow, WorkerStageRow

class _PurchaseClaimLost(RuntimeError):
    pass

class MarketplaceRepository:
    def __init__(self, database_url: str):
        self.engine = create_engine(database_url)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if database_url.startswith("sqlite"): Base.metadata.create_all(self.engine)
    def upsert_provider(self, provider: Provider, wallet_address=None):
        with self.sessions.begin() as s:
            return self._upsert_provider(s,provider,wallet_address)
    def upsert_offering(self, offering: ServiceOffering, *, verified_at=None):
        with self.sessions.begin() as s:
            self._upsert_offering(s,offering,verified_at=verified_at)
    def add_provenance(self, offering_id, registry_id, source_id, payload, cursor=None, etag=None):
        with self.sessions.begin() as s:
            self._add_provenance(s,offering_id,registry_id,source_id,payload,cursor,etag)
    def _upsert_provider(self, session, provider, wallet_address=None):
        now=datetime.now(UTC);row=session.get(ProviderRow,provider.provider_id);owner=wallet_address.lower() if wallet_address else None
        if row and owner and row.wallet_address and row.wallet_address.lower()!=owner:return False
        values=dict(domain=provider.domain.lower(),wallet_address=(row.wallet_address or owner) if row else owner,status=provider.status,payload=provider.model_dump(mode="json"),updated_at=now)
        if row:
            for key,value in values.items():setattr(row,key,value)
        else:session.add(ProviderRow(provider_id=provider.provider_id,domain_failures=0,**values))
        return True
    def _upsert_offering(self, session, offering, *, verified_at=None):
        now=datetime.now(UTC);row=session.get(OfferingRow,offering.offering_id)
        values=dict(provider_id=offering.provider_id,status=offering.status,payload=offering.model_dump(mode="json"),last_verified_at=verified_at or (row.last_verified_at if row else None),updated_at=now)
        if row:
            for key,value in values.items():setattr(row,key,value)
        else:session.add(OfferingRow(offering_id=offering.offering_id,**values))
    def _add_provenance(self, session, offering_id, registry_id, source_id, payload, cursor, etag):
        source_id=self._provenance_source_id(str(source_id))
        now=datetime.now(UTC);row=session.scalar(select(ProvenanceRow).where(ProvenanceRow.offering_id==offering_id,ProvenanceRow.registry_id==registry_id,ProvenanceRow.source_id==source_id))
        if row:row.payload,row.cursor,row.etag,row.updated_at=payload,cursor,etag,now
        else:session.add(ProvenanceRow(offering_id=offering_id,registry_id=registry_id,source_id=source_id,payload=payload,cursor=cursor,etag=etag,updated_at=now))
    @staticmethod
    def _provenance_source_id(source_id):
        if len(source_id)<=512:return source_id
        return f"sha256:{sha256(source_id.encode()).hexdigest()}"
    def get_registry_cursor(self, registry_id):
        with self.sessions() as s:
            row=s.get(RegistryCursorRow,registry_id)
            return {"cursor":row.cursor,"etag":row.etag,"status":row.status,"last_error":row.last_error} if row else {"cursor":None,"etag":None,"status":None,"last_error":None}
    def acquire_registry_lease(self, registry_id, owner_token, *, lease_seconds=120):
        now=datetime.now(UTC);lease_until=now+timedelta(seconds=lease_seconds)
        with self.sessions.begin() as s:
            acquired=s.execute(update(RegistryCursorRow).where(RegistryCursorRow.registry_id==registry_id,or_(RegistryCursorRow.sync_owner_token==owner_token,RegistryCursorRow.sync_lease_until.is_(None),RegistryCursorRow.sync_lease_until<=now)).values(sync_owner_token=owner_token,sync_lease_until=lease_until)).rowcount
            if acquired:return True
            if s.get(RegistryCursorRow,registry_id):return False
            try:
                with s.begin_nested():
                    s.add(RegistryCursorRow(registry_id=registry_id,cursor=None,etag=None,status="running",last_error=None,sync_owner_token=owner_token,sync_lease_until=lease_until,updated_at=now));s.flush()
                return True
            except IntegrityError:return False
    def initialize_registry_cursor(self, registry_id, *, cursor, etag, status):
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            row=s.get(RegistryCursorRow,registry_id)
            if row:return False
            s.add(RegistryCursorRow(registry_id=registry_id,cursor=cursor,etag=etag,status=status,last_error=None,sync_owner_token=None,sync_lease_until=None,updated_at=now))
            return True
    def save_registry_cursor(self, registry_id, *, cursor, etag, status, owner_token=None, last_error=None, release_lease=False, lease_seconds=120):
        if not owner_token:raise ValueError("registry cursor updates require an owner token")
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            values=dict(cursor=cursor,etag=etag,status=status,last_error=last_error,updated_at=now,sync_owner_token=None if release_lease else owner_token,sync_lease_until=None if release_lease else now+timedelta(seconds=lease_seconds))
            return s.execute(update(RegistryCursorRow).where(RegistryCursorRow.registry_id==registry_id,RegistryCursorRow.sync_owner_token==owner_token,RegistryCursorRow.sync_lease_until>now).values(**values)).rowcount==1
    def commit_registry_page(self, registry_id, owner_token, entries, *, cursor, etag, status, last_error=None, release_lease=False, lease_seconds=120):
        now=datetime.now(UTC);lease_until=now+timedelta(seconds=lease_seconds)
        with self.sessions.begin() as s:
            fenced=s.execute(update(RegistryCursorRow).where(RegistryCursorRow.registry_id==registry_id,RegistryCursorRow.sync_owner_token==owner_token,RegistryCursorRow.sync_lease_until>now).values(sync_lease_until=lease_until)).rowcount
            if fenced!=1:return False
            ordered_entries=sorted(entries,key=lambda item:(item[0].provider_id,item[1].offering_id,item[2]))
            providers={}
            for provider,_,_ in ordered_entries:providers.setdefault(provider.provider_id,provider)
            for provider_id in sorted(providers):
                provider=providers[provider_id]
                provider_row=s.get(ProviderRow,provider.provider_id)
                if provider_row and (
                    provider_row.wallet_address is not None
                    or provider_row.status != "discovered"
                ):
                    continue
                self._upsert_provider(s,provider.model_copy(update={"status":"discovered"}))
            s.flush()
            for provider,offering,source_id in ordered_entries:
                offering_row=s.get(OfferingRow,offering.offering_id)
                imported=offering.model_copy(update={"status":"discovered"})
                if offering_row is None:
                    self._upsert_offering(s,imported)
                elif offering_row.status == "disabled":
                    pass
                elif offering_row.status in {"registry_verified","verified","stale","verifying"}:
                    canonical=ServiceOffering.model_validate(offering_row.payload)
                    if self._offering_safety_payload(canonical) != self._offering_safety_payload(imported):
                        offering_row.status="verifying"
                        offering_row.payload={**offering_row.payload,"status":"verifying"}
                        offering_row.candidate_payload=imported.model_copy(update={"status":"verifying"}).model_dump(mode="json")
                        offering_row.candidate_registry_id=registry_id
                        offering_row.updated_at=now
                else:
                    self._upsert_offering(s,imported)
                s.flush()
                self._add_provenance(s,imported.offering_id,registry_id,source_id,imported.model_dump(mode="json"),cursor,etag)
                s.flush()
            values=dict(cursor=cursor,etag=etag,status=status,last_error=last_error,updated_at=now,sync_owner_token=None if release_lease else owner_token,sync_lease_until=None if release_lease else lease_until)
            s.execute(update(RegistryCursorRow).where(RegistryCursorRow.registry_id==registry_id,RegistryCursorRow.sync_owner_token==owner_token).values(**values))
            return True
    @staticmethod
    def _provider_from_row(row):
        if not row:return None
        return Provider.model_validate(row.payload).model_copy(update={
            "provider_id":row.provider_id,
            "domain":row.domain,
            "status":row.status,
        })
    def get_provider(self, provider_id):
        with self.sessions() as s:
            return self._provider_from_row(s.get(ProviderRow,provider_id))
    def get_offering(self, offering_id):
        with self.sessions() as s:
            row=s.get(OfferingRow,offering_id)
            return self._public_offering(row) if row else None
    @staticmethod
    def _trust_tier(status):
        return "registry_verified" if status=="registry_verified" else "clink_verified"
    @classmethod
    def _public_offering(cls,row):
        offering=ServiceOffering.model_validate(row.payload).model_copy(update={"status":row.status})
        if row.status in {"registry_verified","verified"}:
            offering=offering.model_copy(update={"metadata":{
                **offering.metadata,
                "trust_tier":cls._trust_tier(row.status),
                "verification_source":offering.metadata.get("verification_source") or ("external_registry" if row.status=="registry_verified" else "clink_manifest"),
                "last_verified_at":row.last_verified_at.isoformat() if row.last_verified_at else None,
            }})
        return offering
    @staticmethod
    def _offering_safety_payload(offering):
        return {
            "endpoint":offering.endpoint,
            "method":offering.method,
            "payments":[{
                "scheme":item.scheme,"network":item.network,"asset":item.asset,
                "amount_atomic":item.amount_atomic,"pay_to":item.pay_to,
                "price_usd":str(item.price_usd) if item.price_usd is not None else None,
            } for item in offering.payment_options],
        }
    def get_offering_verification_target(self, offering_id):
        snapshot=self.get_offering_verification_snapshot(offering_id)
        return snapshot[0] if snapshot else None
    @staticmethod
    def _verification_payload_hash(payload):
        encoded=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str).encode()
        return "0x"+sha256(encoded).hexdigest()
    def get_offering_verification_snapshot(self, offering_id):
        with self.sessions() as s:
            row=s.get(OfferingRow,offering_id)
            if not row:return None
            payload=row.candidate_payload or row.payload
            offering=ServiceOffering.model_validate(payload).model_copy(update={"status":row.status})
            return offering,self._verification_payload_hash(payload)
    def active_offering(self, offering_id, *, require_verified=True):
        with self.sessions() as s:
            row=s.scalar(select(OfferingRow).join(ProviderRow,ProviderRow.provider_id==OfferingRow.provider_id).where(
                OfferingRow.offering_id==offering_id,
                or_(
                    ProviderRow.status=="active",
                    (ProviderRow.status=="discovered") & (OfferingRow.status=="registry_verified"),
                ),
                *([OfferingRow.status.in_(["registry_verified","verified"])] if require_verified else []),
            ))
            return self._public_offering(row) if row else None
    def suspend_provider(self,provider_id):
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            provider=s.get(ProviderRow,provider_id)
            if not provider:return False
            provider.status="suspended";provider.payload={**provider.payload,"status":"suspended"};provider.updated_at=now
            rows=s.scalars(select(OfferingRow).where(OfferingRow.provider_id==provider_id,OfferingRow.status!="disabled")).all()
            for row in rows:
                row.status="stale";row.payload={**row.payload,"status":"stale"};row.updated_at=now
            return True
    def restore_provider(self,provider_id):
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            provider=s.get(ProviderRow,provider_id)
            if not provider or provider.status!="suspended":return None
            provider.status="wallet_verified";provider.payload={**provider.payload,"status":"wallet_verified"};provider.domain_failures=0;provider.updated_at=now
            return provider.status
    @staticmethod
    def _latest_bazaar_provenance_id():
        return (select(ProvenanceRow.provenance_id)
                .where(ProvenanceRow.offering_id==OfferingRow.offering_id,ProvenanceRow.registry_id=="cdp_bazaar")
                .order_by(ProvenanceRow.updated_at.desc(),ProvenanceRow.provenance_id.desc())
                .limit(1).correlate(OfferingRow).scalar_subquery())
    @staticmethod
    def _bazaar_candidate(offering_row, provider_row, provenance_payload, source_id):
        try:
            offering=ServiceOffering.model_validate(provenance_payload).model_copy(update={
                "offering_id":offering_row.offering_id,
                "provider_id":provider_row.provider_id,
                "source":"cdp_bazaar",
                "source_id":source_id,
                "status":offering_row.status,
            })
            provider_payload=provider_row.payload if isinstance(provider_row.payload,dict) else {}
            provider=Provider(
                provider_id=provider_row.provider_id,
                name=str(provider_payload.get("name") or provider_row.domain),
                domain=provider_row.domain,
                source="cdp_bazaar",
                status=provider_row.status,
                verified_wallets=[],
                metadata=provider_payload.get("metadata",{}),
            )
        except (TypeError,ValueError):return None
        return {"provider":provider,"offering":offering}
    def list_bazaar_candidates(self, *, domain=None, pay_to=None, query=None, limit=20):
        if not 1 <= limit <= 100:raise ValueError("candidate limit must be between 1 and 100")
        latest_id=self._latest_bazaar_provenance_id();batch_size=max(25,min(100,limit*4));scan_budget=max(100,min(500,limit*20))
        result=[];cursor=None;scanned=0;tokens=(query or "").lower().split();normalized_domain=domain.lower().rstrip(".") if domain else None
        with self.sessions() as s:
            while len(result)<limit and scanned<scan_budget:
                fetch_limit=min(batch_size,scan_budget-scanned)
                stmt=(select(OfferingRow,ProviderRow,ProvenanceRow.payload,ProvenanceRow.source_id)
                      .join(ProviderRow,ProviderRow.provider_id==OfferingRow.provider_id)
                      .join(ProvenanceRow,ProvenanceRow.provenance_id==latest_id)
                      .where(OfferingRow.status.in_(["discovered","registry_verified"]),ProviderRow.wallet_address.is_(None))
                      .order_by(OfferingRow.offering_id).limit(fetch_limit))
                if normalized_domain:stmt=stmt.where(ProviderRow.domain==normalized_domain)
                for token in tokens:
                    pattern=f"%{token}%"
                    stmt=stmt.where(or_(
                        func.lower(ProviderRow.domain).like(pattern),
                        func.lower(ProviderRow.payload["name"].as_string()).like(pattern),
                        func.lower(ProvenanceRow.payload["name"].as_string()).like(pattern),
                        func.lower(ProvenanceRow.payload["description"].as_string()).like(pattern),
                        func.lower(ProvenanceRow.payload["endpoint"].as_string()).like(pattern),
                        func.lower(cast(ProvenanceRow.payload["tags"],String)).like(pattern),
                    ))
                if cursor is not None:stmt=stmt.where(OfferingRow.offering_id>cursor)
                rows=s.execute(stmt).all()
                if not rows:break
                scanned+=len(rows)
                cursor=rows[-1][0].offering_id
                for offering_row,provider_row,payload,source_id in rows:
                    candidate=self._bazaar_candidate(offering_row,provider_row,payload,source_id)
                    if not candidate:continue
                    offering,provider=candidate["offering"],candidate["provider"]
                    if pay_to and not any(payment_recipient_matches(option.network,option.pay_to,pay_to) for option in offering.payment_options):continue
                    hay=" ".join([provider.name,provider.domain,offering.name,offering.description,offering.endpoint,*offering.tags]).lower()
                    if tokens and not all(token in hay for token in tokens):continue
                    result.append(candidate)
                    if len(result)>=limit:break
                if len(rows)<fetch_limit:break
        return result
    def get_bazaar_candidate_for_claim(self, offering_id, wallet_address):
        wallet=wallet_address.lower()
        stmt=(select(OfferingRow,ProviderRow,ProvenanceRow.payload,ProvenanceRow.source_id)
              .join(ProviderRow,ProviderRow.provider_id==OfferingRow.provider_id)
              .join(ProvenanceRow,ProvenanceRow.offering_id==OfferingRow.offering_id)
              .where(OfferingRow.offering_id==offering_id,ProvenanceRow.registry_id=="cdp_bazaar")
              .order_by(ProvenanceRow.updated_at.desc(),ProvenanceRow.provenance_id.desc()).limit(1))
        with self.sessions.begin() as s:
            row=s.execute(stmt).first()
            if not row:return "not_found",None
            offering_row,provider_row,payload,source_id=row
            if offering_row.status not in {"discovered","registry_verified"}:return "not_found",None
            if provider_row.wallet_address and provider_row.wallet_address.lower()!=wallet:return "conflict",None
            candidate=self._bazaar_candidate(offering_row,provider_row,payload,source_id)
            return ("candidate",candidate) if candidate else ("not_found",None)
    def create_merchant_session(self, token_hash, wallet_address, expires_at):
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            row=s.get(MerchantSessionRow,token_hash)
            if row:
                row.wallet_address,row.expires_at=wallet_address.lower(),expires_at
            else:s.add(MerchantSessionRow(token_hash=token_hash,wallet_address=wallet_address.lower(),expires_at=expires_at,created_at=now))
    def resolve_merchant_session(self, token):
        token_hash=sha256(token.encode()).hexdigest()
        now=datetime.now(UTC)
        with self.sessions() as s:
            row=s.scalar(select(MerchantSessionRow).where(MerchantSessionRow.token_hash==token_hash,MerchantSessionRow.expires_at>now))
            return row.wallet_address if row else None
    def save_challenge(self, item):
        with self.sessions.begin() as s:
            s.add(ChallengeRow(nonce=item["nonce"],purpose=item["purpose"],subject=item["subject"].lower(),payload=item["payload"],expires_at=item["expires_at"],consumed=item.get("consumed",False)))
    def get_challenge(self, nonce, purpose, subject):
        with self.sessions() as s:
            row=s.scalar(select(ChallengeRow).where(ChallengeRow.nonce==nonce,ChallengeRow.purpose==purpose,ChallengeRow.subject==subject.lower(),ChallengeRow.consumed.is_(False),ChallengeRow.expires_at>datetime.now(UTC)))
            return {"nonce":row.nonce,"purpose":row.purpose,"subject":row.subject,"payload":row.payload,"expires_at":row.expires_at} if row else None
    def consume_challenge(self, nonce, purpose, subject):
        with self.sessions.begin() as s:
            result=s.execute(update(ChallengeRow).where(ChallengeRow.nonce==nonce,ChallengeRow.purpose==purpose,ChallengeRow.subject==subject.lower(),ChallengeRow.consumed.is_(False),ChallengeRow.expires_at>datetime.now(UTC)).values(consumed=True))
            return result.rowcount==1
    def submit_manifest(self, manifest_id, manifest, owner_wallet_address):
        manifest=canonicalize_manifest(manifest)
        now=datetime.now(UTC);owner=owner_wallet_address.lower();digest=manifest_hash(manifest)
        try:
            with self.sessions.begin() as s:
                existing=s.scalar(select(ManifestRow).where(ManifestRow.owner_wallet_address==owner,ManifestRow.manifest_hash==digest))
                if existing:
                    return "existing",existing.manifest_id,existing.status
                s.add(ManifestRow(
                    manifest_id=manifest_id,
                    provider_id=manifest.provider.provider_id,
                    owner_wallet_address=owner,
                    manifest_hash=digest,
                    payload=manifest.model_dump(mode="json"),
                    status="submitted",
                    signer=None,
                    signature=None,
                    updated_at=now,
                ))
                s.flush()
                return "created",manifest_id,"submitted"
        except IntegrityError:
            with self.sessions() as s:
                existing=s.scalar(select(ManifestRow).where(ManifestRow.owner_wallet_address==owner,ManifestRow.manifest_hash==digest))
                if existing:return "existing",existing.manifest_id,existing.status
            return "conflict",None,None
    def mark_manifest_wallet_verified(self, manifest_id, owner_wallet_address, *, signer, signature):
        owner=owner_wallet_address.lower();now=datetime.now(UTC)
        with self.sessions.begin() as s:
            row=s.scalar(select(ManifestRow).where(ManifestRow.manifest_id==manifest_id,ManifestRow.owner_wallet_address==owner))
            if not row:return False
            row.status="wallet_verified";row.signer=signer;row.signature=signature;row.updated_at=now
            return True
    def domain_verification_target(self, provider_id, owner_wallet_address):
        owner=owner_wallet_address.lower()
        with self.sessions() as s:
            stmt=(select(ManifestRow)
                  .where(ManifestRow.provider_id==provider_id,ManifestRow.owner_wallet_address==owner,ManifestRow.status=="wallet_verified")
                  .order_by(ManifestRow.updated_at.desc(),ManifestRow.manifest_id.desc()).limit(1))
            row=s.scalar(stmt)
            if not row:return "manifest_required",None,None
            try:manifest=canonicalize_manifest(ClinkServiceManifest.model_validate(row.payload))
            except (TypeError,ValueError):return "invalid_manifest",None,None
            if manifest.provider.provider_id!=provider_id:return "invalid_manifest",None,None
            provider_row=s.get(ProviderRow,provider_id)
            if provider_row and provider_row.wallet_address and provider_row.wallet_address.lower()!=owner:return "conflict",None,None
            return "ready",row.manifest_id,manifest.provider
    def materialize_manifest_after_domain_verification(self, manifest_id, owner_wallet_address):
        owner=owner_wallet_address.lower();now=datetime.now(UTC);canonical_provider_id=None
        try:
            with self.sessions.begin() as s:
                stmt=select(ManifestRow).where(ManifestRow.manifest_id==manifest_id,ManifestRow.owner_wallet_address==owner,ManifestRow.status=="wallet_verified")
                if self.engine.dialect.name=="postgresql":stmt=stmt.with_for_update()
                row=s.scalar(stmt)
                if not row:return "manifest_required",None
                try:manifest=canonicalize_manifest(ClinkServiceManifest.model_validate(row.payload))
                except (TypeError,ValueError):return "invalid_manifest",None
                canonical_provider_id=manifest.provider.provider_id
                if row.provider_id!=canonical_provider_id:return "invalid_manifest",None
                provider_row=s.get(ProviderRow,canonical_provider_id)
                if provider_row and normalize_provider_domain(provider_row.domain)!=manifest.provider.domain:return "conflict",None
                domain_row=s.scalar(select(ProviderRow).where(ProviderRow.domain==manifest.provider.domain))
                if domain_row and domain_row.provider_id!=canonical_provider_id:return "conflict",None
                if provider_row and provider_row.wallet_address and provider_row.wallet_address.lower()!=owner:return "conflict",None
                offerings=[item.model_copy(update={"provider_id":canonical_provider_id,"status":"submitted"}) for item in manifest.to_offerings()]
                offering_rows={item.offering_id:s.get(OfferingRow,item.offering_id) for item in offerings}
                if any(existing and existing.provider_id!=canonical_provider_id for existing in offering_rows.values()):return "conflict",None

                winner_provider=manifest.provider.model_copy(update={"status":"domain_verified","verified_wallets":[owner]})
                if provider_row:
                    status=provider_row.status if provider_row.status in {"active","suspended"} else "domain_verified"
                    if provider_row.status in {"active","suspended"}:
                        payload={**provider_row.payload,"provider_id":canonical_provider_id,"domain":provider_row.domain,"status":status}
                        wallets=list(payload.get("verified_wallets") or [])
                        if owner not in {str(item).lower() for item in wallets}:wallets.append(owner)
                        payload["verified_wallets"]=wallets
                    else:
                        payload=winner_provider.model_copy(update={"status":status}).model_dump(mode="json")
                    claimed=s.execute(update(ProviderRow).where(
                        ProviderRow.provider_id==canonical_provider_id,
                        or_(ProviderRow.wallet_address.is_(None),func.lower(ProviderRow.wallet_address)==owner),
                    ).values(
                        wallet_address=owner,status=status,payload=payload,domain_failures=0,
                        last_domain_verified_at=now,updated_at=now,
                    )).rowcount
                    if claimed!=1:return "conflict",None
                else:
                    status="domain_verified"
                    s.add(ProviderRow(
                        provider_id=canonical_provider_id,
                        domain=manifest.provider.domain,
                        wallet_address=owner,
                        status=status,
                        payload=winner_provider.model_dump(mode="json"),
                        domain_failures=0,
                        last_domain_verified_at=now,
                        updated_at=now,
                    ))
                    s.flush()
                for item in offerings:
                    existing=offering_rows[item.offering_id]
                    if not existing or existing.status not in {"verifying","verified","stale","disabled"}:
                        self._upsert_offering(s,item)
                return "claimed",status
        except IntegrityError:
            if canonical_provider_id:
                with self.sessions() as s:
                    provider=s.get(ProviderRow,canonical_provider_id)
                    if provider and provider.wallet_address and provider.wallet_address.lower()!=owner:return "conflict",None
            return "conflict",None
    def is_provider_owner(self, provider_id, owner_wallet_address):
        owner=owner_wallet_address.lower()
        with self.sessions() as s:
            return s.scalar(select(ProviderRow.provider_id).where(ProviderRow.provider_id==provider_id,func.lower(ProviderRow.wallet_address)==owner)) is not None
    def get_manifest(self, manifest_id, owner_wallet_address):
        with self.sessions() as s:
            row=s.scalar(select(ManifestRow).where(ManifestRow.manifest_id==manifest_id,ManifestRow.owner_wallet_address==owner_wallet_address.lower()))
            return ClinkServiceManifest.model_validate(row.payload) if row else None
    def list_merchant_manifests(self,owner_wallet_address):
        owner=owner_wallet_address.lower()
        with self.sessions() as s:
            rows=s.scalars(
                select(ManifestRow)
                .where(ManifestRow.owner_wallet_address==owner)
                .order_by(ManifestRow.updated_at.desc(),ManifestRow.manifest_id)
            ).all()
            return [{
                "manifest_id":row.manifest_id,
                "manifest_hash":row.manifest_hash,
                "provider_id":row.provider_id,
                "provider_name":row.payload.get("provider",{}).get("name",row.provider_id),
                "domain":row.payload.get("provider",{}).get("domain"),
                "offering_count":len(row.payload.get("offerings") or []),
                "status":row.status,
                "updated_at":self._console_time(row.updated_at),
            } for row in rows]
    @staticmethod
    def _console_time(value):
        return value.isoformat() if value else None
    @classmethod
    def _console_provider(cls,session,row,*,manifest_owner=None,include_owner=False):
        provider=cls._provider_from_row(row).model_dump(mode="json")
        offering_rows=session.scalars(
            select(OfferingRow)
            .where(OfferingRow.provider_id==row.provider_id)
            .order_by(OfferingRow.offering_id)
        ).all()
        manifest_query=select(ManifestRow).where(ManifestRow.provider_id==row.provider_id)
        if manifest_owner:
            manifest_query=manifest_query.where(ManifestRow.owner_wallet_address==manifest_owner.lower())
        manifest_rows=session.scalars(
            manifest_query.order_by(ManifestRow.updated_at.desc(),ManifestRow.manifest_id)
        ).all()
        result={
            "provider":provider,
            "domain_verification":{
                "failures":row.domain_failures,
                "last_verified_at":cls._console_time(row.last_domain_verified_at),
                "last_check_at":cls._console_time(row.last_domain_check_at),
                "updated_at":cls._console_time(row.updated_at),
            },
            "manifests":[{
                "manifest_id":item.manifest_id,
                "manifest_hash":item.manifest_hash,
                "status":item.status,
                "updated_at":cls._console_time(item.updated_at),
            } for item in manifest_rows],
            "offerings":[{
                "offering_id":item.offering_id,
                "name":item.payload.get("name",item.offering_id),
                "endpoint":item.payload.get("endpoint"),
                "method":item.payload.get("method"),
                "status":item.status,
                "last_verified_at":cls._console_time(item.last_verified_at),
                "last_check_attempt_at":cls._console_time(item.last_check_attempt_at),
                "updated_at":cls._console_time(item.updated_at),
            } for item in offering_rows],
        }
        if include_owner:
            result["owner_wallet_address"]=row.wallet_address
        return result
    def list_merchant_providers(self,owner_wallet_address):
        owner=owner_wallet_address.lower()
        with self.sessions() as s:
            rows=s.scalars(
                select(ProviderRow)
                .where(func.lower(ProviderRow.wallet_address)==owner)
                .order_by(ProviderRow.domain,ProviderRow.provider_id)
            ).all()
            return [self._console_provider(s,row,manifest_owner=owner) for row in rows]
    def merchant_provider_status(self,provider_id,owner_wallet_address):
        owner=owner_wallet_address.lower()
        with self.sessions() as s:
            row=s.scalar(select(ProviderRow).where(
                ProviderRow.provider_id==provider_id,
                func.lower(ProviderRow.wallet_address)==owner,
            ))
            return self._console_provider(s,row,manifest_owner=owner) if row else None
    def list_admin_providers(self,*,query=None,status=None,limit=100):
        with self.sessions() as s:
            statement=select(ProviderRow)
            if status:statement=statement.where(ProviderRow.status==status)
            rows=s.scalars(statement.order_by(ProviderRow.domain,ProviderRow.provider_id)).all()
            if query:
                needle=query.strip().lower()
                rows=[row for row in rows if needle in " ".join((row.provider_id,row.domain,str(row.payload.get("name","")))).lower()]
            return [self._console_provider(s,row,include_owner=True) for row in rows[:limit]]
    @staticmethod
    def _catalog_calls(item):
        quality=item.metadata.get("quality",{})
        if not isinstance(quality,dict):return 0
        value=quality.get("l30DaysTotalCalls",0)
        if isinstance(value,bool):return 0
        try:return max(int(value),0)
        except (TypeError,ValueError):return 0
    @staticmethod
    def _catalog_last_called(item):
        quality=item.metadata.get("quality",{})
        if not isinstance(quality,dict):return float("-inf")
        value=quality.get("lastCalledAt")
        if not isinstance(value,str):return float("-inf")
        try:return datetime.fromisoformat(value.replace("Z","+00:00")).timestamp()
        except ValueError:return float("-inf")
    @classmethod
    def _popular_catalog_key(cls,item):
        return (
            -cls._catalog_calls(item),
            -cls._catalog_last_called(item),
            item.offering_id or "",
        )
    def search(self, query="", network=None, max_price_usd=None, limit=20):
        cutoff=datetime.now(UTC)-timedelta(hours=1)
        with self.sessions() as s: rows=s.scalars(select(OfferingRow).join(ProviderRow,ProviderRow.provider_id==OfferingRow.provider_id).where(
            OfferingRow.status.in_(["registry_verified","verified"]),
            OfferingRow.last_verified_at>=cutoff,
            or_(
                ProviderRow.status=="active",
                (ProviderRow.status=="discovered") & (OfferingRow.status=="registry_verified"),
            ),
        )).all()
        result=[]
        for row in rows:
            item=self._public_offering(row)
            hay=" ".join([item.name,item.description,*item.tags]).lower()
            if query and not all(token in hay for token in query.lower().split()): continue
            options=eligible_payment_options(item.payment_options,network=network,max_price_usd=max_price_usd)
            if (network or max_price_usd is not None) and not options: continue
            result.append(item.model_copy(update={"payment_options":options}))
        if not query.strip():result.sort(key=self._popular_catalog_key)
        return result[:limit]
    def reputation(self, offering_id):
        with self.sessions() as s:
            row=s.scalar(select(ReputationRow).where(ReputationRow.offering_id==offering_id).order_by(ReputationRow.created_at.desc(),ReputationRow.reputation_id.desc()))
            return {"score":row.score,"sample_size":row.sample_size,"confidence":row.confidence,"dimensions":row.dimensions,"weights":WEIGHTS} if row else {"score":50,"sample_size":0,"confidence":0.0,"dimensions":{"identity":100,"quote_consistency":50,"availability":50,"payment_success":50,"delivery_success":50,"dispute":50},"weights":WEIGHTS}
    @staticmethod
    def _reputation_event_payload(row):
        return {
            "offering_id":row.offering_id,
            "purchase_id":row.purchase_id,
            "event_type":row.event_type,
            "dimensions":row.dimensions,
        }
    @staticmethod
    def _same_reputation_event(row, offering_id, event_type, dimensions):
        return (
            row.offering_id == offering_id
            and row.event_type == event_type
            and row.dimensions == dimensions
        )
    @staticmethod
    def _validate_reputation_purchase(row, offering_id, event_type):
        if not row:
            raise ValueError("reputation purchase not found")
        if row.offering_id != offering_id:
            raise ValueError("reputation offering does not match purchase")
        if row.state not in {"delivered", "paid_but_undelivered", "failed"}:
            raise ValueError("reputation purchase is not in a terminal state")
        if row.state != event_type:
            raise ValueError("reputation event type does not match purchase terminal state")
        if row.state == "failed" and row.reason_code in {
            "PREVIEW_EXPIRED",
            "QUOTE_DRIFT",
            "USER_CONFIRMATION_REQUIRED",
            "SPENDING_AUTHORIZATION_REQUIRED",
        }:
            raise ValueError("pre-payment failure is not attributable to the merchant")
    def record_reputation_event(self, offering_id, event_type, purchase_id, dimensions):
        if not isinstance(offering_id,str) or not offering_id or len(offering_id)>64:
            raise ValueError("invalid reputation offering id")
        if not isinstance(purchase_id,str) or not purchase_id or len(purchase_id)>64:
            raise ValueError("invalid reputation purchase id")
        normalized=validate_reputation_event(event_type,dimensions)
        try:
            with self.sessions.begin() as s:
                existing=s.scalar(select(ReputationEventRow).where(ReputationEventRow.purchase_id==purchase_id))
                purchase=s.get(PurchaseRow,purchase_id)
                if existing:
                    if not self._same_reputation_event(existing,offering_id,event_type,normalized):
                        raise ValueError("conflicting reputation event")
                    self._validate_reputation_purchase(purchase,offering_id,event_type)
                    return self._reputation_event_payload(existing)
                self._validate_reputation_purchase(purchase,offering_id,event_type)
                if not s.get(OfferingRow,offering_id):raise ValueError("reputation offering not found")
                row=ReputationEventRow(offering_id=offering_id,purchase_id=purchase_id,event_type=event_type,dimensions=normalized,created_at=datetime.now(UTC))
                s.add(row);s.flush();return self._reputation_event_payload(row)
        except IntegrityError:
            with self.sessions() as s:
                existing=s.scalar(select(ReputationEventRow).where(ReputationEventRow.purchase_id==purchase_id))
                purchase=s.get(PurchaseRow,purchase_id)
                if existing and self._same_reputation_event(existing,offering_id,event_type,normalized):
                    self._validate_reputation_purchase(purchase,offering_id,event_type)
                    return self._reputation_event_payload(existing)
                if existing:raise ValueError("conflicting reputation event")
            raise
    def rebuild_reputation(self, offering_id):
        with self.sessions.begin() as s:
            rows=s.scalars(select(ReputationEventRow).where(ReputationEventRow.offering_id==offering_id).order_by(ReputationEventRow.purchase_id,ReputationEventRow.event_id)).all()
            snapshot=aggregate_reputation_events([
                {"purchase_id":row.purchase_id,"dimensions":row.dimensions}
                for row in rows
            ])
            s.add(ReputationRow(offering_id=offering_id,score=snapshot["score"],sample_size=snapshot["sample_size"],confidence=snapshot["confidence"],dimensions=snapshot["dimensions"],created_at=datetime.now(UTC)))
            return snapshot
    def save_preview(self, preview: PurchasePreview):
        with self.sessions.begin() as s: s.add(PurchasePreviewRow(**preview.model_dump()))
    def get_preview(self, preview_id):
        with self.sessions() as s:
            row=s.get(PurchasePreviewRow,preview_id); return PurchasePreview.model_validate({c.name:getattr(row,c.name) for c in row.__table__.columns}) if row else None
    @staticmethod
    def _purchase_data(purchase, latency_ms=None):
        data=purchase.model_dump();metadata=dict(data.pop("metadata"));metadata.pop("service_result",None);data["metadata_json"]=metadata
        if latency_ms is not None:data["latency_ms"]=max(0,int(latency_ms))
        return data
    @staticmethod
    def _purchase_from_row(row):
        if not row:return None
        fields=("purchase_id","preview_id","offering_id","user_id","state","execution_mode","input_hash","output_hash","reservation_id","action_id","policy_decision_id","receipt_id","audit_event_ids","reason_code","created_at","updated_at")
        data={name:getattr(row,name) for name in fields};data["metadata"]=row.metadata_json
        return Purchase.model_validate(data)
    def save_purchase(self, purchase: Purchase, *, latency_ms=None):
        data=self._purchase_data(purchase,latency_ms)
        with self.sessions.begin() as s:
            row=s.get(PurchaseRow,purchase.purchase_id)
            if row:
                for k,v in data.items(): setattr(row,k,v)
            else: s.add(PurchaseRow(**data))
    @staticmethod
    def _execution_claim_update(purchase_id,allowed_states,expected_execution_mode,now,token,until):
        return update(PurchaseRow).where(
            PurchaseRow.purchase_id==purchase_id,
            PurchaseRow.state.in_(allowed_states),
            PurchaseRow.execution_mode==expected_execution_mode,
            or_(PurchaseRow.execution_claim_token.is_(None),PurchaseRow.execution_claim_until.is_(None),PurchaseRow.execution_claim_until<=now),
        ).values(execution_claim_token=token,execution_claim_until=until).execution_options(synchronize_session=False)
    def claim_purchase_execution(self,purchase,*,allowed_states,expected_execution_mode,lease_seconds=120):
        if purchase.execution_mode!=expected_execution_mode:raise ValueError("purchase execution mode mismatch")
        token=secrets.token_hex(24);now=datetime.now(UTC);until=now+timedelta(seconds=lease_seconds)
        data=self._purchase_data(purchase)
        try:
            with self.sessions.begin() as s:
                row=s.get(PurchaseRow,purchase.purchase_id)
                if row is None:
                    s.add(PurchaseRow(**data,execution_claim_token=token,execution_claim_until=until))
                    s.flush()
                    return purchase,token
                if row.execution_mode!=expected_execution_mode:
                    raise ValueError("purchase execution mode mismatch")
                if row.state not in allowed_states:
                    return self._purchase_from_row(row),None
                claimed=s.execute(self._execution_claim_update(
                    purchase.purchase_id,allowed_states,expected_execution_mode,now,token,until
                )).rowcount
                if claimed==1:
                    s.refresh(row)
                    return self._purchase_from_row(row),token
                s.refresh(row)
                if row.execution_mode!=expected_execution_mode:
                    raise ValueError("purchase execution mode mismatch")
                return self._purchase_from_row(row),None
        except IntegrityError:
            with self.sessions() as s:
                row=s.get(PurchaseRow,purchase.purchase_id)
                if row and row.execution_mode!=expected_execution_mode:
                    raise ValueError("purchase execution mode mismatch")
                return self._purchase_from_row(row),None
    def claim_payment_reconciliations(self,limit=100):
        now=datetime.now(UTC)
        with self.sessions() as s:
            ids=s.scalars(
                select(PurchaseRow.purchase_id)
                .where(
                    PurchaseRow.state=="payment_submitted",
                    or_(PurchaseRow.reason_code.is_(None),PurchaseRow.reason_code!="PAYMENT_MANUAL_REVIEW_REQUIRED"),
                    or_(PurchaseRow.execution_claim_token.is_(None),PurchaseRow.execution_claim_until.is_(None),PurchaseRow.execution_claim_until<=now),
                )
                .order_by(PurchaseRow.updated_at,PurchaseRow.purchase_id)
                .limit(limit)
            ).all()
        claimed=[]
        for purchase_id in ids:
            purchase=self.get_purchase(purchase_id)
            if not purchase:continue
            purchase,token=self.claim_purchase_execution(
                purchase,
                allowed_states={"payment_submitted"},
                expected_execution_mode=purchase.execution_mode,
            )
            if token:claimed.append({"purchase":purchase,"claim_token":token})
        return claimed
    def save_claimed_purchase(self,purchase,claim_token,*,expected_execution_mode,latency_ms=None,release_claim=False,expected_states=None):
        if not claim_token:raise ValueError("purchase execution claim required")
        if purchase.execution_mode!=expected_execution_mode:raise ValueError("purchase execution mode mismatch")
        data=self._purchase_data(purchase,latency_ms)
        data.update(execution_claim_token=None if release_claim else claim_token,execution_claim_until=None if release_claim else datetime.now(UTC)+timedelta(seconds=120))
        with self.sessions.begin() as s:
            conditions=[PurchaseRow.purchase_id==purchase.purchase_id,PurchaseRow.execution_claim_token==claim_token,PurchaseRow.execution_mode==expected_execution_mode]
            if expected_states:conditions.append(PurchaseRow.state.in_(expected_states))
            saved=s.execute(update(PurchaseRow).where(*conditions).values(**data)).rowcount
            if saved!=1:raise RuntimeError("purchase execution claim lost")
        return purchase
    def save_purchase_with_reputation_event(self,purchase,event_type,dimensions,*,claim_token,expected_execution_mode,latency_ms=None,finalization=None,expected_states=None):
        normalized=validate_reputation_event(event_type,dimensions)
        if purchase.execution_mode!=expected_execution_mode:raise ValueError("purchase execution mode mismatch")
        if event_type!=purchase.state:raise ValueError("reputation event type does not match purchase terminal state")
        data=self._purchase_data(purchase,latency_ms)
        data.update(execution_claim_token=None,execution_claim_until=None)
        try:
            with self.sessions.begin() as s:
                existing_event=s.scalar(select(ReputationEventRow).where(ReputationEventRow.purchase_id==purchase.purchase_id))
                current=s.get(PurchaseRow,purchase.purchase_id)
                if current and current.execution_mode!=expected_execution_mode:
                    raise ValueError("purchase execution mode mismatch")
                if existing_event:
                    if not self._same_reputation_event(existing_event,purchase.offering_id,event_type,normalized):
                        raise ValueError("conflicting reputation event")
                    self._validate_reputation_purchase(current,purchase.offering_id,event_type)
                    return self._purchase_from_row(current)
                if not current:raise ValueError("reputation purchase not found")
                if current.offering_id!=purchase.offering_id:raise ValueError("reputation offering does not match purchase")
                if current.state in {"delivered","paid_but_undelivered","failed"}:
                    if current.state!=event_type:raise ValueError("conflicting reputation event")
                else:
                    if not claim_token:raise ValueError("purchase execution claim required")
                    conditions=[PurchaseRow.purchase_id==purchase.purchase_id,PurchaseRow.execution_claim_token==claim_token,PurchaseRow.execution_mode==expected_execution_mode]
                    if expected_states:conditions.append(PurchaseRow.state.in_(expected_states))
                    saved=s.execute(update(PurchaseRow).where(*conditions).values(**data)).rowcount
                    if saved!=1:
                        raise _PurchaseClaimLost
                    current=s.get(PurchaseRow,purchase.purchase_id)
                    s.refresh(current)
                self._validate_reputation_purchase(current,purchase.offering_id,event_type)
                event_row=ReputationEventRow(offering_id=purchase.offering_id,purchase_id=purchase.purchase_id,event_type=event_type,dimensions=normalized,created_at=datetime.now(UTC))
                s.add(event_row)
                if finalization:
                    outbox=s.scalar(select(PurchaseFinalizationRow).where(PurchaseFinalizationRow.purchase_id==purchase.purchase_id))
                    values=dict(target_state=finalization["target_state"],payload=finalization["payload"],updated_at=datetime.now(UTC))
                    if outbox:
                        outbox.target_state,outbox.payload,outbox.updated_at=values["target_state"],values["payload"],values["updated_at"]
                    else:
                        s.add(PurchaseFinalizationRow(purchase_id=purchase.purchase_id,attempts=0,created_at=datetime.now(UTC),**values))
                s.flush()
                return self._purchase_from_row(current)
        except (IntegrityError,_PurchaseClaimLost) as error:
            with self.sessions() as s:
                existing=s.scalar(select(ReputationEventRow).where(ReputationEventRow.purchase_id==purchase.purchase_id))
                current=s.get(PurchaseRow,purchase.purchase_id)
                if current and current.execution_mode!=expected_execution_mode:
                    raise ValueError("purchase execution mode mismatch")
                if existing and self._same_reputation_event(existing,purchase.offering_id,event_type,normalized):
                    self._validate_reputation_purchase(current,purchase.offering_id,event_type)
                    return self._purchase_from_row(current)
                if existing:raise ValueError("conflicting reputation event")
            if isinstance(error,_PurchaseClaimLost):
                raise RuntimeError("purchase execution claim lost") from error
            raise
    def get_purchase(self,purchase_id):
        with self.sessions() as s:
            return self._purchase_from_row(s.get(PurchaseRow,purchase_id))
    def stats(self):
        with self.sessions() as s:
            return {"providers":len(s.scalars(select(ProviderRow)).all()),"offerings":len(s.scalars(select(OfferingRow)).all()),"verified":len(s.scalars(select(OfferingRow).where(OfferingRow.status=="verified")).all())}
    def pilot_metrics(self):
        with self.sessions() as s:
            candidate_offerings = s.scalar(
                select(func.count(func.distinct(OfferingRow.offering_id)))
                .select_from(OfferingRow)
                .join(ProviderRow, ProviderRow.provider_id == OfferingRow.provider_id)
                .join(ProvenanceRow, ProvenanceRow.offering_id == OfferingRow.offering_id)
                .where(
                    OfferingRow.status == "discovered",
                    ProviderRow.wallet_address.is_(None),
                    ProvenanceRow.registry_id == "cdp_bazaar",
                )
            )
            claimed_providers = s.scalar(
                select(func.count())
                .select_from(ProviderRow)
                .where(ProviderRow.wallet_address.is_not(None))
            )
            verified_offerings = s.scalar(
                select(func.count())
                .select_from(OfferingRow)
                .where(OfferingRow.status == "verified")
            )
            registry_verified_offerings = s.scalar(
                select(func.count())
                .select_from(OfferingRow)
                .where(OfferingRow.status == "registry_verified")
            )
            stale_offerings = s.scalar(
                select(func.count())
                .select_from(OfferingRow)
                .where(OfferingRow.status == "stale")
            )
        return {
            "candidate_offerings": candidate_offerings or 0,
            "claimed_providers": claimed_providers or 0,
            "verified_offerings": (verified_offerings or 0)+(registry_verified_offerings or 0),
            "registry_verified_offerings": registry_verified_offerings or 0,
            "clink_verified_offerings": verified_offerings or 0,
            "stale_offerings": stale_offerings or 0,
        }
    def bazaar_target_coverage(self, targets):
        expected={item.name.lower():item for item in targets}
        coverage={key:{"offering_ids":set(),"registry_verified_ids":set(),"clink_verified_ids":set(),"claimed":False} for key in expected}
        with self.sessions() as s:
            rows=s.execute(
                select(OfferingRow,ProviderRow,ProvenanceRow.payload)
                .join(ProviderRow,ProviderRow.provider_id==OfferingRow.provider_id)
                .join(ProvenanceRow,ProvenanceRow.offering_id==OfferingRow.offering_id)
                .where(ProvenanceRow.registry_id=="cdp_bazaar")
            ).all()
        for offering,provider,payload in rows:
            metadata=(payload or {}).get("metadata",{}) if isinstance(payload,dict) else {}
            markers=metadata.get("bazaar_targets",[]) if isinstance(metadata,dict) else []
            for marker in markers if isinstance(markers,list) else []:
                name=str(marker.get("name") or "").lower() if isinstance(marker,dict) else ""
                if name not in coverage:continue
                item=coverage[name]
                item["offering_ids"].add(offering.offering_id)
                item["claimed"] = item["claimed"] or provider.wallet_address is not None
                if offering.status=="registry_verified":
                    item["registry_verified_ids"].add(offering.offering_id)
                if offering.status=="verified" and provider.status=="active":
                    item["clink_verified_ids"].add(offering.offering_id)
        result=[]
        for target in targets:
            item=coverage[target.name.lower()]
            registry_verified=len(item["registry_verified_ids"])
            clink_verified=len(item["clink_verified_ids"])
            all_verified=item["registry_verified_ids"]|item["clink_verified_ids"]
            candidates=len(item["offering_ids"]-all_verified)
            status=(
                "clink_verified" if clink_verified else
                "registry_verified" if registry_verified else
                "claimed" if item["claimed"] else
                "discovered" if candidates else
                "missing"
            )
            result.append({
                "name":target.name,"category":target.category,"status":status,
                "candidate_offerings":candidates,
                "registry_verified_offerings":registry_verified,
                "clink_verified_offerings":clink_verified,
                "verified_offerings":registry_verified+clink_verified,
            })
        return result
    @staticmethod
    def _aware(value):
        if value is None:
            return None
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    def registry_health(self, freshness_timeout_seconds=900, expected_registry_ids=()):
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=freshness_timeout_seconds)
        with self.sessions() as s:
            rows = {
                row.registry_id: row
                for row in s.scalars(
                    select(RegistryCursorRow).order_by(RegistryCursorRow.registry_id)
                ).all()
            }
        result = []
        for registry_id in sorted(set(rows) | set(expected_registry_ids)):
            row = rows.get(registry_id)
            if not row:
                result.append({
                    "registry_id": registry_id,
                    "status": "missing",
                    "raw_status": None,
                    "last_error": "registry has not completed an initial sync",
                    "updated_at": None,
                })
                continue
            updated_at = self._aware(row.updated_at)
            status = row.status
            if status in {"succeeded", "running"} and updated_at < cutoff:
                status = "stale"
            result.append({
                "registry_id": row.registry_id,
                "status": status,
                "raw_status": row.status,
                "last_error": row.last_error,
                "updated_at": updated_at.isoformat(),
            })
        return result
    def due_offerings(self,cutoff,limit=20):
        with self.sessions() as s:
            rows = s.scalars(
                select(OfferingRow).join(ProviderRow,ProviderRow.provider_id==OfferingRow.provider_id).where(
                    or_(
                        (ProviderRow.status=="active") & OfferingRow.status.in_(["verified", "stale", "verifying"]),
                        (ProviderRow.status=="discovered") & OfferingRow.status.in_(["discovered","registry_verified","stale","verifying"]) & OfferingRow.offering_id.in_(select(ProvenanceRow.offering_id)),
                    ),
                    or_(
                        OfferingRow.last_check_attempt_at.is_(None),
                        OfferingRow.last_check_attempt_at < cutoff,
                    ),
                ).order_by(OfferingRow.last_check_attempt_at.asc().nullsfirst(),OfferingRow.offering_id)
            ).all()
            offerings=[ServiceOffering.model_validate(row.candidate_payload or row.payload).model_copy(update={"status":row.status}) for row in rows]
            offerings.sort(key=lambda item:(
                not bool(item.metadata.get("bazaar_targets")),
                item.offering_id,
            ))
            return offerings[:limit]
    def mark_offering_check_attempt(self,offering_id,cutoff=None,attempted_at=None):
        attempted_at=attempted_at or datetime.now(UTC)
        with self.sessions.begin() as s:
            conditions=[OfferingRow.offering_id==offering_id,OfferingRow.status!="disabled",OfferingRow.provider_id.in_(select(ProviderRow.provider_id).where(ProviderRow.status.in_(["active","discovered"])))]
            if cutoff is not None:conditions.append(or_(OfferingRow.last_check_attempt_at.is_(None),OfferingRow.last_check_attempt_at<cutoff))
            return s.execute(update(OfferingRow).where(*conditions).values(last_check_attempt_at=attempted_at,updated_at=attempted_at)).rowcount==1
    def complete_offering_verification(self,offering_id,success,*,expected_payload_hash,checked_at=None):
        checked_at=checked_at or datetime.now(UTC)
        with self.sessions.begin() as s:
            snapshot=s.get(OfferingRow,offering_id)
            if not snapshot:
                return {"applied":False,"status":"missing","reason":"offering_not_found"}
            provider=s.scalar(
                select(ProviderRow)
                .where(ProviderRow.provider_id==snapshot.provider_id)
                .with_for_update()
            )
            row=s.scalar(
                select(OfferingRow)
                .where(OfferingRow.offering_id==offering_id)
                .with_for_update()
            )
            if (
                not provider
                or not row
                or row.provider_id!=snapshot.provider_id
                or provider.status not in {"discovered","domain_verified","active"}
                or row.status=="disabled"
            ):
                return {
                    "applied":False,
                    "status":row.status if row else "missing",
                    "reason":"verification_state_changed",
                }
            current_payload=row.candidate_payload or row.payload
            if self._verification_payload_hash(current_payload)!=expected_payload_hash:
                return {
                    "applied":False,
                    "status":row.status,
                    "reason":"verification_target_changed",
                }
            row.last_check_attempt_at=checked_at;row.updated_at=checked_at
            if success:
                registry_tier=provider.status=="discovered"
                registry_id=s.scalar(
                    select(ProvenanceRow.registry_id)
                    .where(ProvenanceRow.offering_id==offering_id)
                    .order_by(ProvenanceRow.updated_at.desc(),ProvenanceRow.provenance_id.desc())
                    .limit(1)
                ) if registry_tier else None
                if registry_tier and not registry_id:
                    return {"applied":False,"status":row.status,"reason":"registry_provenance_required"}
                next_status="registry_verified" if registry_tier else "verified"
                metadata={
                    **(current_payload.get("metadata") or {}),
                    "trust_tier":"registry_verified" if registry_tier else "clink_verified",
                    "verification_source":registry_id if registry_tier else "clink_manifest",
                }
                if row.candidate_payload:
                    row.payload={**row.candidate_payload,"status":next_status,"metadata":metadata}
                    row.candidate_payload=None;row.candidate_registry_id=None
                else:row.payload={**row.payload,"status":next_status,"metadata":metadata}
                row.status=next_status;row.last_verified_at=checked_at
                if provider.status=="domain_verified":
                    provider.status="active"
                    provider.payload={**provider.payload,"status":"active"}
                    provider.updated_at=checked_at
            else:
                row.status="stale";row.payload={**row.payload,"status":"stale"}
            return {"applied":True,"status":row.status,"reason":None}
    def record_offering_check(self,offering_id,success,*,checked_at=None):
        snapshot=self.get_offering_verification_snapshot(offering_id)
        if not snapshot:return False
        return self.complete_offering_verification(
            offering_id,success,expected_payload_hash=snapshot[1],checked_at=checked_at
        )["applied"]
    def heartbeat(self,worker_id,status):
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            row=s.get(WorkerHeartbeatRow,worker_id)
            if row:row.status,row.updated_at=status,now
            else:s.add(WorkerHeartbeatRow(worker_id=worker_id,status=status,updated_at=now))
    def start_worker_stage(self,worker_id,stage,cycle_token):
        now = datetime.now(UTC)
        with self.sessions.begin() as s:
            row = s.get(WorkerStageRow, (worker_id, stage))
            if row:
                row.cycle_token=cycle_token;row.started_at=now;row.completed_at=None
                row.status="running";row.last_error=None;row.updated_at=now
            else:
                s.add(WorkerStageRow(
                    worker_id=worker_id,stage=stage,cycle_token=cycle_token,status="running",
                    last_error=None,started_at=now,completed_at=None,updated_at=now,
                ))
        return True
    def complete_worker_stage(self,worker_id,stage,cycle_token,status,*,last_error=None):
        if status=="running":raise ValueError("worker stage completion must be terminal")
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            return s.execute(update(WorkerStageRow).where(
                WorkerStageRow.worker_id==worker_id,WorkerStageRow.stage==stage,
                WorkerStageRow.cycle_token==cycle_token,WorkerStageRow.status=="running",
            ).values(status=status,last_error=last_error,completed_at=now,updated_at=now)).rowcount==1
    def record_worker_stage(self, worker_id, stage, status, *, last_error=None):
        cycle_token=secrets.token_hex(16)
        self.start_worker_stage(worker_id,stage,cycle_token)
        if status!="running":return self.complete_worker_stage(worker_id,stage,cycle_token,status,last_error=last_error)
        return True
    def worker_stage_health(self, worker_id):
        with self.sessions() as s:
            rows = s.scalars(
                select(WorkerStageRow)
                .where(WorkerStageRow.worker_id == worker_id)
                .order_by(WorkerStageRow.stage)
            ).all()
        return {
            row.stage: {
                "status": row.status,
                "cycle_token":row.cycle_token,
                "last_error": row.last_error,
                "started_at": self._aware(row.started_at).isoformat(),
                "completed_at": self._aware(row.completed_at).isoformat() if row.completed_at else None,
                "updated_at": self._aware(row.updated_at).isoformat(),
            }
            for row in rows
        }
    def worker_health(self, timeout_seconds, *, stage_timeout_seconds=120, mandatory_stages=()):
        cutoff = datetime.now(UTC) - timedelta(seconds=timeout_seconds)
        with self.sessions() as s:
            row = s.scalar(
                select(WorkerHeartbeatRow)
                .order_by(WorkerHeartbeatRow.updated_at.desc(), WorkerHeartbeatRow.worker_id)
                .limit(1)
            )
        if not row:
            return {"status": "missing", "worker_id": None, "updated_at": None, "stages": {}}
        updated_at = self._aware(row.updated_at)
        status = "ok" if row.status == "running" and updated_at >= cutoff else (
            "stale" if updated_at < cutoff else "failed"
        )
        stages=self.worker_stage_health(row.worker_id);now=datetime.now(UTC)
        for stage in mandatory_stages:
            state=stages.get(stage)
            if not state:
                stages[stage]={"status":"missing","last_error":"stage has not completed","started_at":None,"completed_at":None,"updated_at":None,"cycle_token":None}
                if status=="ok":status="degraded"
            elif state["status"]=="failed":
                if status=="ok":status="degraded"
            elif state["status"]=="running":
                started=datetime.fromisoformat(state["started_at"])
                if now-started>timedelta(seconds=stage_timeout_seconds):
                    state["status"]="timed_out"
                    if status=="ok":status="degraded"
        cycle_tokens={stages[stage].get("cycle_token") for stage in mandatory_stages if stages.get(stage) and stages[stage].get("status")!="missing"}
        cycle_status="incomplete"
        def parse_stage_timestamp(value):
            if not value:
                return None
            try:
                return datetime.fromisoformat(value)
            except (TypeError, ValueError):
                return None
        def ordered_stage_sequence(stage_states):
            previous_completed_at=None
            for index,state in enumerate(stage_states):
                started_at=parse_stage_timestamp(state.get("started_at"))
                if started_at is None:
                    return False
                if state["status"]=="running":
                    if index!=len(stage_states)-1:
                        return False
                    if previous_completed_at is not None:
                        try:
                            if started_at<previous_completed_at:
                                return False
                        except TypeError:
                            return False
                    continue
                if state["status"]!="succeeded":
                    return False
                completed_at=parse_stage_timestamp(state.get("completed_at"))
                if completed_at is None:
                    return False
                try:
                    if completed_at<started_at or (
                        previous_completed_at is not None
                        and started_at<previous_completed_at
                    ):
                        return False
                except TypeError:
                    return False
                previous_completed_at=completed_at
            return bool(stage_states)
        if mandatory_stages:
            tokens=[stages[stage].get("cycle_token") for stage in mandatory_stages]
            stage_statuses=[stages[stage]["status"] for stage in mandatory_stages]
            stage_states=[stages[stage] for stage in mandatory_stages]
            current_token=tokens[0]
            all_stages_healthy=all(state in {"succeeded", "running"} for state in stage_statuses)
            if current_token and all_stages_healthy:
                if len(cycle_tokens)==1 and all(token==current_token for token in tokens):
                    if all(state=="succeeded" for state in stage_statuses) and ordered_stage_sequence(stage_states):
                        cycle_status="complete"
                    elif (
                        stage_statuses[-1]=="running"
                        and all(state=="succeeded" for state in stage_statuses[:-1])
                        and ordered_stage_sequence(stage_states)
                    ):
                        cycle_status="running"
                elif len(cycle_tokens)==2:
                    previous_tokens={token for token in tokens if token!=current_token}
                    prefix_length=0
                    while prefix_length<len(tokens) and tokens[prefix_length]==current_token:
                        prefix_length+=1
                    prefix_statuses=stage_statuses[:prefix_length]
                    suffix_statuses=stage_statuses[prefix_length:]
                    prefix_states=stage_states[:prefix_length]
                    suffix_states=stage_states[prefix_length:]
                    previous_token=next(iter(previous_tokens), None)
                    current_started_at=[
                        parse_stage_timestamp(state.get("started_at"))
                        for state in prefix_states
                    ]
                    previous_completed_at=[
                        parse_stage_timestamp(state.get("completed_at"))
                        for state in suffix_states
                    ]
                    if (
                        len(previous_tokens)==1
                        and prefix_length
                        and prefix_length<len(tokens)
                        and all(token==previous_token for token in tokens[prefix_length:])
                        and all(state=="succeeded" for state in suffix_statuses)
                        and all(state=="succeeded" for state in prefix_statuses[:-1])
                        and prefix_statuses[-1] in {"succeeded", "running"}
                        and ordered_stage_sequence(prefix_states)
                        and ordered_stage_sequence(suffix_states)
                        and all(timestamp is not None for timestamp in current_started_at)
                        and all(timestamp is not None for timestamp in previous_completed_at)
                    ):
                        try:
                            if min(current_started_at)>max(previous_completed_at):
                                cycle_status="running"
                        except TypeError:
                            pass
        if mandatory_stages and cycle_status not in {"complete", "running"} and status=="ok":status="degraded"
        return {
            "status": status,
            "cycle_status":cycle_status,
            "worker_id": row.worker_id,
            "updated_at": updated_at.isoformat(),
            "stages": stages,
        }
    def due_providers(self,cutoff):
        with self.sessions() as s:
            rows=s.scalars(select(ProviderRow).where(ProviderRow.status.in_(["domain_verified","active"]),(ProviderRow.last_domain_check_at.is_(None))|(ProviderRow.last_domain_check_at<cutoff))).all()
            return [(Provider.model_validate(row.payload),row.wallet_address) for row in rows]
    def mark_domain_check_attempt(self,provider_id,cutoff=None,attempted_at=None):
        attempted_at=attempted_at or datetime.now(UTC)
        with self.sessions.begin() as s:
            conditions=[ProviderRow.provider_id==provider_id,ProviderRow.status.in_(["domain_verified","active"])]
            if cutoff is not None:conditions.append(or_(ProviderRow.last_domain_check_at.is_(None),ProviderRow.last_domain_check_at<cutoff))
            return s.execute(update(ProviderRow).where(*conditions).values(last_domain_check_at=attempted_at,updated_at=attempted_at)).rowcount==1
    def record_domain_check(self,provider_id,success,checked_at=None):
        checked_at=checked_at or datetime.now(UTC)
        with self.sessions.begin() as s:
            row=s.get(ProviderRow,provider_id)
            if not row:return False
            row.last_domain_check_at=checked_at;row.updated_at=checked_at
            if success:row.domain_failures=0;row.last_domain_verified_at=checked_at
            else:
                row.domain_failures+=1
                if row.domain_failures>=3:
                    row.status="suspended";row.payload={**row.payload,"status":"suspended"}
                    offerings=s.scalars(select(OfferingRow).where(OfferingRow.provider_id==provider_id,OfferingRow.status!="disabled")).all()
                    for offering in offerings:
                        offering.status="stale";offering.payload={**offering.payload,"status":"stale"};offering.updated_at=checked_at
            return True
    def worker_ready(self,timeout_seconds):
        return self.worker_health(timeout_seconds)["status"] == "ok"
    def enqueue_finalization(self,purchase_id,target_state,payload):
        now=datetime.now(UTC)
        with self.sessions.begin() as s:
            row=s.scalar(select(PurchaseFinalizationRow).where(PurchaseFinalizationRow.purchase_id==purchase_id))
            if row:row.target_state,row.payload,row.updated_at=target_state,payload,now
            else:s.add(PurchaseFinalizationRow(purchase_id=purchase_id,target_state=target_state,payload=payload,attempts=0,created_at=now,updated_at=now))
    def claim_finalizations(self,_legacy_token=None,lease_seconds=120,limit=20):
        now=datetime.now(UTC);until=now+timedelta(seconds=lease_seconds)
        with self.sessions.begin() as s:
            stmt=select(PurchaseFinalizationRow).where((PurchaseFinalizationRow.claimed_until.is_(None))|(PurchaseFinalizationRow.claimed_until<now)).limit(limit)
            if self.engine.dialect.name=="postgresql":stmt=stmt.with_for_update(skip_locked=True)
            rows=s.scalars(stmt).all()
            for row in rows:row.claim_token,row.claimed_until=secrets.token_hex(24),until
            return [{"outbox_id":r.outbox_id,"purchase_id":r.purchase_id,"target_state":r.target_state,"payload":r.payload,"claim_token":r.claim_token} for r in rows]
    def finish_finalization(self,outbox_id,token,error=None):
        with self.sessions.begin() as s:
            row=s.get(PurchaseFinalizationRow,outbox_id)
            if not row or row.claim_token!=token:return False
            if error:
                row.attempts+=1;row.last_error=error;row.claim_token=None;row.claimed_until=None;row.updated_at=datetime.now(UTC)
            else:s.delete(row)
            return True
    def complete_finalization_for_purchase(self,purchase_id):
        with self.sessions.begin() as s:
            row=s.scalar(select(PurchaseFinalizationRow).where(PurchaseFinalizationRow.purchase_id==purchase_id))
            if row:s.delete(row)
