from __future__ import annotations

import os
import socket
import secrets
import time
from datetime import UTC, datetime, timedelta

from adapters.cdp_bazaar import CdpBazaarAdapter
from adapters.clink_peer import ClinkPeerAdapter
from services.core_gateway import HttpCoreGateway
from services.domain_verification import DomainVerifier
from services.marketplace_repository import MarketplaceRepository
from services.provider_verification import EndpointVerifier
from services.purchase_service import PurchaseService
from services.registry_aggregation import RegistryAggregator
from shared.config import AppConfig
from shared.ephemeral import EphemeralStore


MANDATORY_STAGES=("registry_sync","offering_verify","domain_verify","purchase_finalization")

def _run_stage(repository, worker_id, cycle_token, stage, operation):
    repository.start_worker_stage(worker_id,stage,cycle_token)
    try:
        result = operation()
    except Exception as exc:
        state = {"status": "failed", "last_error": str(exc)}
        repository.complete_worker_stage(worker_id,stage,cycle_token,"failed",last_error=str(exc))
        return state
    state = {"status": "succeeded", "last_error": None, "result": result}
    if not repository.complete_worker_stage(worker_id,stage,cycle_token,"succeeded"):
        return {"status":"failed","last_error":"worker stage cycle claim lost"}
    return state


def _verify_offerings(
    repository,
    verifier,
    interval_seconds,
    *,
    batch_size=5,
    progress_callback=None,
):
    cutoff = datetime.now(UTC) - timedelta(seconds=interval_seconds)
    checked = 0
    applied = 0
    not_applied = 0
    for offering in repository.due_offerings(cutoff, limit=batch_size):
        try:
            if not repository.mark_offering_check_attempt(offering.offering_id,cutoff):continue
            snapshot=repository.get_offering_verification_snapshot(offering.offering_id)
            if not snapshot:
                not_applied+=1
                continue
            target,payload_hash=snapshot
            result = verifier.verify(target)
            completion=repository.complete_offering_verification(
                offering.offering_id,result.verified,expected_payload_hash=payload_hash
            )
            if completion["applied"]:applied+=1
            else:not_applied+=1
            checked += 1
        finally:
            if progress_callback:
                progress_callback()
    return {"checked":checked,"applied":applied,"not_applied":not_applied}


def _sync_registries(repository, registry_aggregator):
    results = registry_aggregator.sync()
    failures = []
    for item in results:
        registry_id = item.get("registry_id")
        raw_status = item.get("status")
        if not registry_id or raw_status == "busy":
            continue
        cursor = repository.get_registry_cursor(registry_id)
        repository.initialize_registry_cursor(
            registry_id,
            cursor=cursor["cursor"],
            etag=cursor["etag"],
            status="pending",
        )
        owner_token = secrets.token_urlsafe(24)
        if not repository.acquire_registry_lease(registry_id, owner_token):
            continue
        status = (
            "succeeded" if raw_status in {"ok", "succeeded"} else
            "running" if raw_status == "in_progress" else
            "failed"
        )
        last_error = None if status in {"succeeded","running"} else str(
            item.get("reason") or item.get("last_error") or raw_status
        )
        current = repository.get_registry_cursor(registry_id)
        if not repository.save_registry_cursor(
            registry_id,
            cursor=current["cursor"],
            etag=current["etag"],
            status=status,
            owner_token=owner_token,
            last_error=last_error,
            release_lease=True,
        ):
            failures.append(f"{registry_id}: registry cursor lease lost")
        elif status == "failed":
            failures.append(f"{registry_id}: {last_error}")
    if failures:
        raise RuntimeError("; ".join(failures))
    return results


def _verify_domains(repository, domain_verifier, interval_seconds):
    cutoff = datetime.now(UTC) - timedelta(seconds=interval_seconds)
    checked = 0
    failed = 0
    for provider, wallet in repository.due_providers(cutoff):
        if not repository.mark_domain_check_attempt(provider.provider_id,cutoff):continue
        try:
            domain_verifier.verify(
                domain=provider.domain,
                provider_id=provider.provider_id,
                wallet_address=wallet,
            )
            repository.record_domain_check(provider.provider_id, True)
        except Exception:
            failed += 1
            repository.record_domain_check(provider.provider_id, False)
        checked += 1
    return {"checked": checked, "failed": failed}


def _retry_finalizations(repository, purchases):
    completed = 0
    failed = 0
    reconciled = 0
    errors = []
    for item in repository.claim_payment_reconciliations():
        purchase=item["purchase"]
        claim_token=item["claim_token"]
        try:
            purchases.process_reconciliation(purchase,claim_token)
            reconciled+=1
        except Exception as exc:
            waiting=purchase.model_copy(update={
                "reason_code":"PAYMENT_RECONCILIATION_ERROR",
                "metadata":{**purchase.metadata,"settlement":{**(purchase.metadata.get("settlement") or {}),"next_action":"reconcile_payment"}},
                "updated_at":datetime.now(UTC),
            })
            try:
                repository.save_claimed_purchase(
                    waiting,
                    claim_token,
                    expected_execution_mode=purchase.execution_mode,
                    release_claim=True,
                    expected_states={"payment_submitted"},
                )
            except Exception as claim_exc:
                errors.append(str(claim_exc))
            failed+=1
            errors.append(str(exc))
    for item in repository.claim_finalizations():
        claim_token=item["claim_token"]
        try:
            purchases.process_finalization(item)
            if not repository.finish_finalization(item["outbox_id"],claim_token):
                raise RuntimeError("purchase finalization claim lost")
            completed += 1
        except Exception as exc:
            if not repository.finish_finalization(item["outbox_id"],claim_token,str(exc)):
                errors.append("purchase finalization claim lost")
                failed+=1
                continue
            failed += 1
            errors.append(str(exc))
    if errors:
        raise RuntimeError("; ".join(errors))
    return {"reconciled":reconciled,"completed": completed, "failed": failed}


def run_cycle(
    repository,
    registry_aggregator,
    verifier,
    domain_verifier,
    purchases=None,
    worker_id="worker",
    *,
    offering_verify_interval_seconds=900,
    offering_verify_batch_size=5,
    domain_verify_interval_seconds=86400,
    progress_callback=None,
):
    stages = {};cycle_token=secrets.token_hex(24)
    stages["registry_sync"] = _run_stage(
        repository,
        worker_id,
        cycle_token,
        "registry_sync",
        lambda: _sync_registries(repository, registry_aggregator),
    )
    stages["offering_verify"] = _run_stage(
        repository,
        worker_id,
        cycle_token,
        "offering_verify",
        lambda: _verify_offerings(
            repository,
            verifier,
            offering_verify_interval_seconds,
            batch_size=offering_verify_batch_size,
            progress_callback=progress_callback,
        ),
    )
    stages["domain_verify"] = _run_stage(
        repository,
        worker_id,
        cycle_token,
        "domain_verify",
        lambda: _verify_domains(
            repository, domain_verifier, domain_verify_interval_seconds
        ),
    )
    stages["purchase_finalization"] = _run_stage(
        repository,
        worker_id,
        cycle_token,
        "purchase_finalization",
        lambda: _retry_finalizations(repository, purchases)
        if purchases
        else {"completed": 0, "failed": 0},
    )
    stages["heartbeat"] = _run_stage(
        repository,
        worker_id,
        cycle_token,
        "heartbeat",
        lambda: repository.heartbeat(worker_id, "running"),
    )
    return stages


def _build_aggregator(config, repository, *, progress_callback=None):
    adapters = {
        "cdp_bazaar": CdpBazaarAdapter(
            search_url=config.bazaar_search_url,
            resources_url=config.bazaar_resources_url,
            timeout_seconds=config.bazaar_request_timeout_seconds,
        )
    }
    adapters.update({
        str(item.get("id") or f"peer_{index}"): ClinkPeerAdapter(str(item["url"]))
        for index, item in enumerate(config.peer_registries)
        if item.get("url")
    })
    return RegistryAggregator(
        repository,
        adapters,
        page_size=config.bazaar_sync_page_size,
        max_pages=config.bazaar_sync_max_pages,
        targeted_supply=config.bazaar_targets,
        progress_callback=progress_callback,
    )


def _build_purchase_service(config, repository, core):
    return PurchaseService(
        repository,
        core,
        preview_ttl=config.purchase_preview_ttl_seconds,
        ephemeral_store=EphemeralStore(config.redis_url),
        native_provider_ids=config.native_provider_ids,
        registry_verified_max_price_usd=config.registry_verified_max_price_usd,
        public_base_url=config.public_base_url,
        eip3009_domains=config.eip3009_domains,
    )


def main():
    config = AppConfig.from_env()
    repository = MarketplaceRepository(config.database_url)
    configured=os.getenv("MARKETPLACE_WORKER_ID")
    worker_id=f"{configured or socket.gethostname()}-{secrets.token_hex(16)}"
    core = HttpCoreGateway(
        action_url=config.core_action_url,
        policy_url=config.core_policy_url,
        audit_url=config.core_audit_url,
        funding_url=config.core_funding_url,
        account_url=config.core_account_url,
        token=config.core_internal_api_token,
    )
    purchases = _build_purchase_service(config, repository, core)
    progress_callback = lambda: repository.heartbeat(worker_id, "running")
    aggregator = _build_aggregator(
        config,
        repository,
        progress_callback=progress_callback,
    )
    verifier = EndpointVerifier(
        timeout_seconds=config.endpoint_verify_timeout_seconds,
        request_attempts=config.endpoint_verify_attempts,
    )
    domain_verifier = DomainVerifier()
    while True:
        progress_callback()
        run_cycle(
            repository,
            aggregator,
            verifier,
            domain_verifier,
            purchases,
            worker_id,
            offering_verify_interval_seconds=config.offering_verify_interval_seconds,
            offering_verify_batch_size=config.offering_verify_batch_size,
            domain_verify_interval_seconds=config.domain_verify_interval_seconds,
            progress_callback=progress_callback,
        )
        time.sleep(config.worker_cycle_interval_seconds)


if __name__ == "__main__":
    main()
