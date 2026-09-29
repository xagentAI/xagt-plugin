from __future__ import annotations

import base64
import json
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import patch
from urllib.parse import urlsplit

from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from fastapi.testclient import TestClient
from sqlalchemy import inspect, text

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from adapters.cdp_bazaar import CdpBazaarAdapter
from mcp_servers import marketplace_server
from services import marketplace_app
from services.domain_verification import DomainVerifier
from services.identity_service import IdentityService
from services.marketplace_repository import MarketplaceRepository
from services.provider_verification import EndpointVerifier
from services.purchase_service import PurchaseService
from services.registry_aggregation import RegistryAggregator
from shared.config import AppConfig
from shared.ephemeral import EphemeralStore
from shared.manifest import ManifestClaim


PAY_TO = "0x1111111111111111111111111111111111111111"
USDC_POLYGON = "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359"
AGENT_TOKEN = "bazaar-pilot-agent-token"
SIWE_DOMAIN = "marketplace.clink.local"
PRIVATE_INPUT = "pilot-private-input-must-not-persist"


def _resource(index: int, *, name: str) -> dict[str, Any]:
    return {
        "resource": f"https://risk-{index}.example.com/v1/check",
        "serviceName": name,
        "description": "Deterministic wallet risk screening fixture",
        "tags": ["wallet", "risk"],
        "x402Version": 2,
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:137",
                "asset": USDC_POLYGON,
                "amount": "5000",
                "payTo": PAY_TO,
            }
        ],
        "extensions": {"bazaar": {"info": {"input": {"method": "POST"}}}},
    }


class FixtureBazaarAdapter:
    def __init__(self) -> None:
        self.pages = {
            0: {
                "items": [_resource(1, name="Pilot Wallet Risk")],
                "offset": 0,
                "count": 1,
                "total": 2,
                "etag": "pilot-page-1",
            },
            1: {
                "items": [_resource(2, name="Secondary Wallet Risk")],
                "offset": 1,
                "count": 1,
                "total": 2,
            },
        }
        self.requests: list[dict[str, Any]] = []

    def fetch_page(self, *, offset: int, limit: int, etag: str | None) -> dict[str, Any]:
        self.requests.append({"offset": offset, "limit": limit, "etag": etag})
        return self.pages[offset]

    @staticmethod
    def normalize_resource(resource: dict[str, Any]):
        return CdpBazaarAdapter().normalize_resource(resource)


class DomainResponse:
    def __init__(self, url: str, provider_id: str, wallet_address: str) -> None:
        self.url = url
        self._payload = {
            "provider_id": provider_id,
            "wallet_address": wallet_address,
        }

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return self._payload


class DomainClient:
    def __init__(self, provider_id: str, wallet_address: str) -> None:
        self.provider_id = provider_id
        self.wallet_address = wallet_address

    def get(self, url: str, **_: Any) -> DomainResponse:
        return DomainResponse(url, self.provider_id, self.wallet_address)


class PaymentRequiredResponse:
    status_code = 402

    def __init__(self) -> None:
        payload = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:137",
                    "asset": USDC_POLYGON,
                    "amount": "5000",
                    "payTo": PAY_TO,
                }
            ],
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii").rstrip("=")
        self.headers = {"PAYMENT-REQUIRED": encoded}


class PaymentRequiredSession:
    def request(self, **_: Any) -> PaymentRequiredResponse:
        return PaymentRequiredResponse()


class MerchantResponse:
    is_success = True
    headers = {"content-type": "application/json"}

    @staticmethod
    def json() -> dict[str, str]:
        return {"status": "ok", "risk": "low"}


class MerchantClient:
    def __init__(self) -> None:
        self.deliveries = 0

    def request(self, *_: Any, **__: Any) -> MerchantResponse:
        self.deliveries += 1
        return MerchantResponse()


class FakeCore:
    def __init__(self) -> None:
        self.reserve_calls = 0
        self.settle_calls = 0
        self.finalize_calls = 0

    @staticmethod
    def create_action(_: dict[str, Any]) -> dict[str, str]:
        return {"action_id": "action_bazaar_pilot"}

    @staticmethod
    def evaluate_policy(_: dict[str, Any]) -> dict[str, Any]:
        return {
            "policy_decision_id": "policy_bazaar_pilot",
            "approved": True,
        }

    @staticmethod
    def update_action(*_: Any, **__: Any) -> dict[str, str]:
        return {"state": "policy_approved"}

    @staticmethod
    def audit(_: dict[str, Any]) -> dict[str, str]:
        return {"event_id": "audit_bazaar_pilot"}

    @staticmethod
    def funding_readiness() -> dict[str, str]:
        return {"spender_address": "0x" + "4" * 40}

    @staticmethod
    def resolve_authorization(payload: dict[str, Any]) -> dict[str, Any]:
        result = {
            "ready": True,
            "authorization_rail": payload["authorization_rail"],
            "wallet_identity_id": "wallet_identity_bazaar_pilot",
            "spending_grant_id": "spending_grant_bazaar_pilot",
        }
        if payload["authorization_rail"] == "native_allowance":
            result["asset_allowance_id"] = "asset_allowance_bazaar_pilot"
        return result

    def reserve(self, _: dict[str, Any]) -> dict[str, str]:
        self.reserve_calls += 1
        return {"reservation_id": "reservation_bazaar_pilot"}

    def settle(self, _: str, __: dict[str, Any]) -> dict[str, Any]:
        self.settle_calls += 1
        return {
            "state": "settled",
            "receipt_id": "receipt_bazaar_pilot",
            "tx_hash": "0xbazaarpilot",
            "receipt": {
                "receipt_id": "receipt_bazaar_pilot",
                "status": "settled",
            },
        }

    def finalize(self, _: str, __: dict[str, Any]) -> dict[str, str]:
        self.finalize_calls += 1
        return {"state": "finalized"}

    @staticmethod
    def reservation(_: str) -> dict[str, str]:
        return {"state": "settled", "receipt_id": "receipt_bazaar_pilot"}

    @staticmethod
    def health() -> dict[str, str]:
        return {"status": "ok"}


def _response_json(response, expected_status: int = 200) -> dict[str, Any]:
    if response.status_code != expected_status:
        raise AssertionError(
            f"unexpected HTTP {response.status_code}: {response.text}"
        )
    return response.json()


def _merchant_session(client: TestClient, account) -> str:
    challenge = _response_json(
        client.post(
            "/auth/siwe/challenge",
            json={"address": account.address, "domain": SIWE_DOMAIN},
        )
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge["message"]), account.key
    ).signature.hex()
    verified = _response_json(
        client.post(
            "/auth/siwe/verify",
            json={
                "address": account.address,
                "nonce": challenge["nonce"],
                "message": challenge["message"],
                "signature": signature,
            },
        )
    )
    return verified["access_token"]


def _persisted_database_text(repository: MarketplaceRepository) -> str:
    inspector = inspect(repository.engine)
    records: dict[str, list[dict[str, Any]]] = {}
    with repository.engine.connect() as connection:
        for table_name in inspector.get_table_names():
            rows = connection.execute(
                text(f'SELECT * FROM "{table_name}"')
            ).mappings().all()
            records[table_name] = [dict(row) for row in rows]
    return json.dumps(records, sort_keys=True, default=str)


def run_smoke() -> dict[str, Any]:
    with TemporaryDirectory(prefix="clink-bazaar-pilot-") as directory:
        database_url = f"sqlite+pysqlite:///{Path(directory) / 'marketplace.sqlite3'}"
        repository = MarketplaceRepository(database_url)
        adapter = FixtureBazaarAdapter()
        sync = RegistryAggregator(
            repository,
            {"cdp_bazaar": adapter},
            page_size=1,
            max_pages=3,
        ).sync_registry("cdp_bazaar")
        if sync["status"] != "succeeded" or [item["offset"] for item in adapter.requests] != [0, 1]:
            raise AssertionError(f"Bazaar fixture pagination failed: {sync}")

        account = Account.from_key("0x" + "11" * 32)
        provider, candidate = CdpBazaarAdapter().normalize_resource(
            _resource(1, name="Pilot Wallet Risk")
        )
        domain_verifier = DomainVerifier(
            client=DomainClient(provider.provider_id, account.address),
            resolver=lambda host: (host, [], ["93.184.216.34"]),
        )
        endpoint_verifier = EndpointVerifier(
            session=PaymentRequiredSession(),
            resolver=lambda _: ["93.184.216.34"],
        )
        core = FakeCore()
        merchant_client = MerchantClient()
        config = replace(
            AppConfig.from_env(),
            database_url=database_url,
            redis_url="",
            internal_api_token=AGENT_TOKEN,
            admin_disabled=True,
            native_provider_ids=(provider.provider_id,),
            peer_registries=(),
            siwe_allowed_domains=(SIWE_DOMAIN,),
        )
        purchase_service_class = PurchaseService

        def purchase_service_factory(repo, core_gateway, *, preview_ttl, **_: Any):
            return purchase_service_class(
                repo,
                core_gateway,
                preview_ttl=preview_ttl,
                client=merchant_client,
                ephemeral_store=EphemeralStore(),
                native_provider_ids=config.native_provider_ids,
            )

        with (
            patch.object(marketplace_app, "DomainVerifier", return_value=domain_verifier),
            patch.object(
                marketplace_app,
                "PurchaseService",
                side_effect=purchase_service_factory,
            ),
        ):
            app = marketplace_app.create_marketplace_app(
                config,
                repository,
                IdentityService(repository),
                core=core,
                endpoint_verifier=endpoint_verifier,
            )
        with TestClient(app) as client:
            unverified_public = _response_json(
                client.post("/catalog/search", json={"query": "pilot wallet risk"})
            )
            if unverified_public["count"] != 0:
                raise AssertionError("unverified Bazaar candidate leaked into public catalog")

            merchant_token = _merchant_session(client, account)
            merchant_headers = {"Authorization": f"Bearer {merchant_token}"}
            candidates = _response_json(
                client.get(
                    "/merchant/candidates",
                    params={"query": "pilot wallet risk"},
                    headers=merchant_headers,
                )
            )
            candidate_record = next(
                item
                for item in candidates["candidates"]
                if item["offering"]["offering_id"] == candidate.offering_id
            )
            draft = _response_json(
                client.post(
                    f"/merchant/candidates/{candidate.offering_id}/claim-draft",
                    headers=merchant_headers,
                )
            )["manifest"]
            submitted = _response_json(
                client.post(
                    "/merchant/manifests",
                    headers=merchant_headers,
                    json=draft,
                )
            )
            claim_response = _response_json(
                client.post(
                    f"/merchant/manifests/{submitted['manifest_id']}/claim-challenge",
                    headers=merchant_headers,
                )
            )
            claim = ManifestClaim.model_validate(claim_response["claim"])
            claim_signature = Account.sign_message(
                encode_typed_data(full_message=claim.typed_data()), account.key
            ).signature.hex()
            _response_json(
                client.post(
                    f"/merchant/manifests/{submitted['manifest_id']}/submit-claim",
                    headers=merchant_headers,
                    json={
                        "claim": claim.model_dump(mode="json"),
                        "signature": claim_signature,
                        "wallet_address": account.address,
                    },
                )
            )
            _response_json(
                client.post(
                    f"/merchant/providers/{provider.provider_id}/verify-domain",
                    headers=merchant_headers,
                )
            )
            verified = _response_json(
                client.post(
                    f"/merchant/offerings/{candidate.offering_id}/verify",
                    headers=merchant_headers,
                )
            )

            agent_headers = {"Authorization": f"Bearer {AGENT_TOKEN}"}

            def mcp_request(url: str, payload: dict[str, Any] | None = None):
                path = urlsplit(url).path
                headers = agent_headers if path.startswith("/purchases") else {}
                response = (
                    client.get(path, headers=headers)
                    if payload is None
                    else client.post(path, headers=headers, json=payload)
                )
                return _response_json(response)

            with patch.object(
                marketplace_server,
                "_request_json",
                side_effect=mcp_request,
            ):
                public_search = marketplace_server.search_clink_services(
                    "pilot wallet risk"
                )
                quotes = marketplace_server.compare_clink_service_quotes(
                    "pilot wallet risk"
                )
                if len(quotes["quotes"]) != 1:
                    raise AssertionError(f"unexpected quote set: {quotes}")
                preview = marketplace_server.create_clink_purchase_preview(
                    "hermes-pilot-user",
                    candidate.offering_id,
                    {"wallet": PRIVATE_INPUT},
                )
                first = marketplace_server.execute_clink_purchase(
                    preview["preview_id"],
                    user_confirmed=True,
                    spending_authorization_id="spending_auth_bazaar_pilot",
                )
                replay = marketplace_server.execute_clink_purchase(
                    preview["preview_id"],
                    user_confirmed=True,
                    spending_authorization_id="spending_auth_bazaar_pilot",
                )
                stored = marketplace_server.get_clink_purchase(
                    first["purchase"]["purchase_id"]
                )

        reputation = repository.rebuild_reputation(candidate.offering_id)
        persisted = _persisted_database_text(repository)
        plaintext_found = (
            PRIVATE_INPUT in persisted
            or '"service_result"' in persisted
            or '"risk": "low"' in persisted
        )
        if stored["input_hash"] != preview["input_hash"] or not stored["output_hash"]:
            raise AssertionError("purchase input/output hashes were not persisted")
        if plaintext_found:
            raise AssertionError("plaintext input or output was persisted")
        if core.reserve_calls != 1 or core.settle_calls != 1 or merchant_client.deliveries != 1:
            raise AssertionError("purchase replay repeated payment or delivery")

        purchase = first["purchase"]
        result = {
            "status": "ok",
            "sync": sync,
            "candidate": candidate_record["offering"],
            "unverified_public_count": unverified_public["count"],
            "verified": verified,
            "public_search": public_search,
            "quote_count": len(quotes["quotes"]),
            "preview_id": preview["preview_id"],
            "purchase": purchase,
            "service_result": first["service_result"],
            "replay_service_result": replay["service_result"],
            "core_calls": {
                "reserve": core.reserve_calls,
                "settle": core.settle_calls,
            },
            "merchant_deliveries": merchant_client.deliveries,
            "reputation": reputation,
            "persistence": {
                "input_hash": stored["input_hash"],
                "output_hash": stored["output_hash"],
                "plaintext_found": plaintext_found,
            },
            "references": {
                "action_id": purchase["action_id"],
                "policy_decision_id": purchase["policy_decision_id"],
                "receipt_id": purchase["receipt_id"],
                "audit_event_ids": purchase["audit_event_ids"],
            },
        }

        assert result["purchase"]["state"] == "delivered"
        assert result["service_result"] == {"status": "ok", "risk": "low"}
        assert result["replay_service_result"] is None
        assert result["reputation"]["sample_size"] == 1
        assert all(result["references"].values())
        return result


def main() -> None:
    print(json.dumps(run_smoke(), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
