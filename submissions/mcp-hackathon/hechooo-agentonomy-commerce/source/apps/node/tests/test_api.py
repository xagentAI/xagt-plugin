from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from apps.node.clink_node.adapters.core import AccountProxyResponse
from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.api import NodeApiContext, create_app
from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.interactions import InteractionService
from apps.node.clink_node.paths import NodePaths
from apps.node.clink_node.storage.base import ModuleRecord
from apps.node.clink_node.storage.sqlite import SQLiteNodeRepository


class FakeCoreAdapter:
    def __init__(self) -> None:
        self.created_for: list[str] = []
        self.audit_requests: list[tuple[str, int]] = []

    def health(self) -> dict:
        return {"status": "ok"}

    def account_readiness(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "wallet_bound": True,
            "wallet_address": "0x1111111111111111111111111111111111111111",
            "wallet_identity_id": "wallet_identity_1",
            "spending_grant_active": True,
            "active_spending_mandate": {
                "spending_grant_id": "grant_1",
                "agent_id": "hermes",
                "limits_usdc": {
                    "per_transaction": "0.1",
                    "rolling_hour": "1",
                    "daily": "5",
                    "total": "10",
                },
                "remaining_usdc": {
                    "rolling_hour": "0.9",
                    "daily": "4.8",
                    "total": "9.8",
                },
                "product_scopes": [
                    "marketplace",
                    "prediction_markets",
                ],
                "network_scopes": ["eip155:137", "eip155:8453"],
                "asset_scopes": ["USDC"],
                "expires_at": "2026-08-23T12:00:00Z",
            },
            "chain_allowances": {
                "eip155:137": True,
                "eip155:8453": True,
            },
            "ready": True,
        }

    def audit_summary(self, user_id: str, limit: int) -> list[dict]:
        self.audit_requests.append((user_id, limit))
        return [
            {
                "event": "Spending mandate authorized",
                "summary": "Recorded by Clink Account",
                "at": "2026-07-23T10:00:00Z",
            }
        ]

    def create_account_session(self, user_id: str) -> dict:
        self.created_for.append(user_id)
        return {
            "account_url": f"http://core.test/account/{user_id}",
            "expires_at": "2026-07-23T12:00:00Z",
        }

    def proxy_account_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> AccountProxyResponse:
        self.proxied_request = {
            "method": method,
            "path": path,
            "query": query,
            "headers": headers,
            "body": body,
        }
        return AccountProxyResponse(
            status_code=303,
            content=b"",
            headers=(
                ("location", "/account"),
                (
                    "set-cookie",
                    "clink_account_session=s1; Path=/account; Secure",
                ),
                (
                    "set-cookie",
                    "clink_account_csrf=c1; Path=/account; Secure",
                ),
            ),
        )


class FakeBusinessAdapter:
    def __init__(self, name: str, capabilities: list[str]) -> None:
        self.name = name
        self._capabilities = capabilities
        self.proxied_requests: list[dict] = []
        self.service_requests: list[int] = []
        self.service_error: DownstreamError | None = None
        self.service_result = {
            "count": 1,
            "services": [
                {
                    "offering_id": "service_1",
                    "name": "Risk API",
                    "description": "Screen one address.",
                    "starting_price_usd": "0.007",
                    "networks": ["eip155:8453"],
                    "trust_tier": "registry_verified",
                    "calls_30d": 23,
                    "category": "data",
                    "subcategory": "risk_identity",
                    "icon_key": "service-111111111111",
                    "icon_text": "RA",
                }
            ],
        }

    def health(self) -> dict:
        return {"status": "ok"}

    def capabilities(self) -> list[dict]:
        return [
            {"name": name, "module": self.name}
            for name in self._capabilities
        ]

    def list_services(self, limit: int = 20) -> dict:
        self.service_requests.append(limit)
        if self.service_error is not None:
            raise self.service_error
        return self.service_result

    def proxy_public_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> AccountProxyResponse:
        self.proxied_requests.append(
            {
                "method": method,
                "path": path,
                "query": query,
                "headers": headers,
                "body": body,
            }
        )
        return AccountProxyResponse(
            status_code=200,
            content=f"{self.name}:{path}".encode(),
            headers=(("content-type", "text/plain"),),
        )


class FakePredictionMarketsAdapter(FakeBusinessAdapter):
    def __init__(self, capabilities: list[str]) -> None:
        super().__init__("prediction-markets", capabilities)
        self.binding = {
            "binding_id": "pm_binding_1",
            "status": "active",
            "wallet_address": "0x1111111111111111111111111111111111111111",
            "funder_address": "0x1111111111111111111111111111111111111111",
            "account_mode": "eoa",
            "polymarket_signature_type": "0",
            "has_api_credentials": True,
            "api_key_fingerprint": "sha256:must-not-leak",
            "next_action": "account_binding_active",
        }

    def account_status(self, user_id: str) -> dict:
        return {**self.binding, "user_id": user_id}


class NodeApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        paths = NodePaths.from_home(root / ".clink")
        self.settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=paths,
        )
        repository = SQLiteNodeRepository(root / "node.db")
        repository.migrate()
        now = datetime.now(UTC)
        for name in ("core", "marketplace", "prediction-markets"):
            repository.set_module(
                ModuleRecord(
                    name=name,
                    mode="managed",
                    status="ready",
                    pid=100,
                    endpoint=f"http://{name}.test",
                    mcp_url=None,
                    detail=None,
                    updated_at=now,
                )
            )
        self.core = FakeCoreAdapter()
        interaction_service = InteractionService(
            repository,
            base_url="http://127.0.0.1:8170",
        )
        context = NodeApiContext(
            settings=self.settings,
            repository=repository,
            interaction_service=interaction_service,
            session_token="local-session-secret",
            core=self.core,
            marketplace=FakeBusinessAdapter(
                "marketplace",
                ["search_clink_services", "execute_clink_purchase"],
            ),
            prediction_markets=FakePredictionMarketsAdapter(
                [
                    "search_prediction_markets",
                    "execute_prediction_market_order_preview",
                ],
            ),
        )
        self.client = TestClient(create_app(context))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_health_and_ready_are_distinct(self) -> None:
        health = self.client.get("/healthz")
        ready = self.client.get("/readyz")

        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["status"], "ready")

    def test_disabled_miniapp_api_router_has_no_redirect_variants(
        self,
    ) -> None:
        for method, path in (
            ("post", "/miniapp/api/session/"),
            ("get", "/miniapp/api/chat/"),
            ("post", "/miniapp/api/operations/account/"),
        ):
            with self.subTest(method=method, path=path):
                response = getattr(self.client, method)(
                    path,
                    follow_redirects=False,
                )
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("location", response.headers)

    def test_companion_is_served_by_the_unified_node_api(self) -> None:
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Agentonomy", response.text)
        self.assertIn('id="marketplace-services"', response.text)

    def test_node_and_capability_projection(self) -> None:
        node = self.client.get("/v1/node").json()
        capabilities = self.client.get("/v1/capabilities").json()

        self.assertEqual(node["profile"], "personal")
        self.assertEqual(node["storage"]["backend"], "sqlite")
        self.assertEqual(capabilities["count"], 4)
        self.assertIn(
            "execute_clink_purchase",
            {item["name"] for item in capabilities["capabilities"]},
        )

    def test_marketplace_services_are_public_read_only_projection(
        self,
    ) -> None:
        response = self.client.get(
            "/v1/marketplace/services",
            params={"limit": 12},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        service = response.json()["services"][0]
        self.assertEqual(service["category"], "data")
        self.assertEqual(service["subcategory"], "risk_identity")
        self.assertEqual(service["icon_key"], "service-111111111111")
        self.assertEqual(service["icon_text"], "RA")
        self.assertEqual(
            self.client.app.state.context.marketplace.service_requests,
            [12],
        )
        self.assertEqual(
            self.client.get(
                "/v1/marketplace/services",
                params={"limit": 21},
            ).status_code,
            422,
        )

    def test_marketplace_catalog_failure_is_isolated_from_account(
        self,
    ) -> None:
        marketplace = self.client.app.state.context.marketplace
        marketplace.service_error = DownstreamError(
            "marketplace",
            503,
            "private downstream detail",
        )

        catalog = self.client.get("/v1/marketplace/services")
        account = self.client.get(
            "/v1/account/summary",
            params={"user_id": "telegram_jeff"},
        )

        self.assertEqual(catalog.status_code, 503)
        self.assertEqual(
            catalog.json()["detail"],
            "Marketplace service catalog unavailable",
        )
        self.assertNotIn("private downstream detail", catalog.text)
        self.assertEqual(account.status_code, 200)

    def test_account_readiness_is_projected_from_core(self) -> None:
        response = self.client.get(
            "/v1/account/readiness",
            params={"user_id": "telegram_jeff"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ready"])
        self.assertTrue(response.json()["wallet_bound"])

    def test_unified_account_summary_projects_core_and_products(self) -> None:
        response = self.client.get(
            "/v1/account/summary",
            params={"user_id": "telegram_jeff"},
        )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ready")
        self.assertTrue(body["core"]["ready"])
        self.assertTrue(body["products"]["marketplace"]["ready"])
        prediction = body["products"]["prediction_markets"]
        self.assertTrue(prediction["ready"])
        self.assertEqual(
            prediction["account"]["binding_id"],
            "pm_binding_1",
        )
        self.assertEqual(prediction["account"]["account_mode"], "eoa")
        self.assertNotIn("api_key_fingerprint", response.text)

    def test_unified_account_summary_degrades_only_prediction_product(
        self,
    ) -> None:
        prediction = self.client.app.state.context.prediction_markets
        prediction.binding = {
            "status": "unavailable",
            "next_action": "create_polymarket_account_binding",
        }

        body = self.client.get(
            "/v1/account/summary",
            params={"user_id": "telegram_jeff"},
        ).json()

        self.assertEqual(body["status"], "attention_required")
        self.assertTrue(body["core"]["ready"])
        self.assertTrue(body["products"]["marketplace"]["ready"])
        self.assertFalse(body["products"]["prediction_markets"]["ready"])
        self.assertEqual(
            body["products"]["prediction_markets"]["next_action"],
            "create_polymarket_account_binding",
        )

    def test_activity_is_projected_from_core_audit_summary(self) -> None:
        response = self.client.get(
            "/v1/activity",
            params={"user_id": "telegram_jeff", "limit": 12},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(
            response.json()["items"][0]["event"],
            "Spending mandate authorized",
        )
        self.assertEqual(self.core.audit_requests, [("telegram_jeff", 12)])

    def test_mutation_requires_local_session_token(self) -> None:
        rejected = self.client.post(
            "/v1/account/sessions",
            json={"user_id": "telegram_jeff"},
        )
        accepted = self.client.post(
            "/v1/account/sessions",
            headers={"Authorization": "Bearer local-session-secret"},
            json={"user_id": "telegram_jeff"},
        )

        self.assertEqual(rejected.status_code, 401)
        self.assertEqual(accepted.status_code, 201)
        self.assertEqual(self.core.created_for, ["telegram_jeff"])

    def test_account_console_is_proxied_through_unified_node(self) -> None:
        response = self.client.post(
            "/account/session_1?source=telegram",
            headers={
                "Content-Type": "application/json",
                "Cookie": "existing=value",
            },
            content=b"{}",
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/account")
        self.assertEqual(
            response.headers.get_list("set-cookie"),
            [
                "clink_account_session=s1; Path=/account; Secure",
                "clink_account_csrf=c1; Path=/account; Secure",
            ],
        )
        self.assertEqual(
            self.core.proxied_request["path"],
            "/account/session_1",
        )
        self.assertEqual(
            self.core.proxied_request["query"],
            "source=telegram",
        )
        self.assertEqual(self.core.proxied_request["body"], b"{}")

    def test_business_signing_pages_are_proxied_through_node(self) -> None:
        marketplace = self.client.get(
            "/x402/checkout/purchase_1?token=one-time",
        )
        marketplace_asset = self.client.get(
            "/assets/x402_checkout.js",
        )
        binding = self.client.get(
            "/polymarket/binding-console/session_1?access_token=token",
        )
        order = self.client.post(
            "/execution/polymarket/order-signing-sessions/session_1/complete",
            json={"signed_order": {}},
        )

        self.assertEqual(marketplace.status_code, 200)
        self.assertEqual(marketplace_asset.status_code, 200)
        self.assertEqual(binding.status_code, 200)
        self.assertEqual(order.status_code, 200)
        self.assertEqual(
            self.client.app.state.context.marketplace.proxied_requests[0][
                "path"
            ],
            "/x402/checkout/purchase_1",
        )
        self.assertEqual(
            self.client.app.state.context.prediction_markets.proxied_requests[
                0
            ]["path"],
            "/polymarket/binding-console/session_1",
        )

    def test_business_proxy_does_not_expose_admin_or_internal_routes(
        self,
    ) -> None:
        self.assertEqual(self.client.get("/merchant").status_code, 404)
        self.assertEqual(
            self.client.get("/internal/polymarket/bindings/latest/u1").status_code,
            404,
        )

    def test_business_proxy_caps_post_body_before_adapter_io(self) -> None:
        marker = b"must-not-echo-" + b"x" * (64 * 1024)
        response = self.client.post(
            "/execution/polymarket/"
            "browser-order-signing-session/complete",
            headers={
                "Content-Type": "application/json",
                "Content-Length": "1",
            },
            content=marker,
        )

        self.assertEqual(response.status_code, 413)
        self.assertNotIn("must-not-echo", response.text)
        self.assertEqual(
            self.client.app.state.context.prediction_markets.proxied_requests,
            [],
        )

    def test_business_proxy_rejects_duplicate_content_length(self) -> None:
        response = self.client.post(
            "/execution/polymarket/"
            "browser-order-signing-session/complete",
            headers=[
                ("Content-Type", "application/json"),
                ("Content-Length", "2"),
                ("Content-Length", "2"),
            ],
            content=b"{}",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            self.client.app.state.context.prediction_markets.proxied_requests,
            [],
        )

    def test_interaction_payload_requires_one_time_token(self) -> None:
        created = self.client.post(
            "/v1/interactions",
            headers={"Authorization": "Bearer local-session-secret"},
            json={
                "kind": "wallet_approval",
                "user_id": "telegram_jeff",
                "payload": {"request_id": "req_1"},
            },
        )
        body = created.json()
        token = body["url"].split("#token=", 1)[1]

        missing = self.client.post(
            f"/v1/interactions/{body['session_id']}/consume",
            json={"token": "wrong-token-long-enough"},
        )
        consumed = self.client.post(
            f"/v1/interactions/{body['session_id']}/consume",
            json={"token": token},
        )
        replay = self.client.post(
            f"/v1/interactions/{body['session_id']}/consume",
            json={"token": token},
        )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(consumed.status_code, 200)
        self.assertEqual(consumed.json()["payload"]["request_id"], "req_1")
        self.assertEqual(replay.status_code, 404)

    def test_ready_reports_not_ready_when_a_module_failed(self) -> None:
        record = self.client.app.state.context.repository.get_module(
            "marketplace"
        )
        self.client.app.state.context.repository.set_module(
            ModuleRecord(
                name=record.name,
                mode=record.mode,
                status="failed",
                pid=record.pid,
                endpoint=record.endpoint,
                mcp_url=record.mcp_url,
                detail="worker exited",
                updated_at=datetime.now(UTC),
            )
        )

        response = self.client.get("/readyz")

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["status"], "not_ready")
        self.assertEqual(
            response.json()["modules"]["marketplace"]["status"],
            "failed",
        )


if __name__ == "__main__":
    unittest.main()
