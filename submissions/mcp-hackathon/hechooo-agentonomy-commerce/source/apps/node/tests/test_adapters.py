from __future__ import annotations

import json
import unittest

import httpx

from apps.node.clink_node.adapters.core import CoreHttpAdapter
from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.adapters.marketplace import MarketplaceHttpAdapter
from apps.node.clink_node.adapters.prediction_markets import (
    PredictionMarketsHttpAdapter,
)


class AdapterTests(unittest.TestCase):
    def test_balance_reads_use_internal_user_scoped_endpoints(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/internal/account-balances":
                return httpx.Response(
                    200,
                    json={
                        "user_id": "u1",
                        "status": "ready",
                        "wallet_bound": True,
                        "wallet_address": "0x" + "11" * 20,
                        "balances": {},
                    },
                )
            if request.url.path == "/polymarket/account-balance":
                return httpx.Response(
                    200,
                    json={
                        "status": "ready",
                        "user_id": "u1",
                        "venue": "polymarket",
                        "venue_wallet_address": "0x" + "22" * 20,
                        "asset": "USDC",
                        "available_amount_atomic": "2000000",
                        "available_amount_usdc": "2.000000",
                    },
                )
            return httpx.Response(404)

        transport = httpx.MockTransport(handler)
        core = CoreHttpAdapter(
            account_url="http://core.test",
            action_url="http://action.test",
            policy_url="http://policy.test",
            audit_url="http://audit.test",
            funding_url="http://funding.test",
            internal_token="secret-token",
            transport=transport,
        )
        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            funding_url="http://funding.test",
            internal_token="secret-token",
            transport=transport,
        )

        self.assertEqual(core.wallet_balances("u1")["status"], "ready")
        self.assertEqual(
            prediction.account_balance("u1")["available_amount_usdc"],
            "2.000000",
        )
        self.assertEqual(
            [request.url.params["user_id"] for request in requests],
            ["u1", "u1"],
        )
        self.assertTrue(
            all(
                request.headers["authorization"] == "Bearer secret-token"
                for request in requests
            )
        )

    def test_core_requests_use_internal_bearer_token(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/internal/account-readiness":
                return httpx.Response(
                    200,
                    json={"user_id": "u1", "ready": True},
                )
            if request.url.path == "/internal/account-sessions":
                return httpx.Response(
                    201,
                    json={"account_url": "http://node/account/s1"},
                )
            if request.url.path == "/audit/summary":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "event": "Wallet bound",
                            "summary": "Recorded by Clink Account",
                            "at": "2026-07-23T10:00:00Z",
                        }
                    ],
                )
            return httpx.Response(200, json={"status": "ok"})

        adapter = CoreHttpAdapter(
            account_url="http://core.test",
            action_url="http://action.test",
            policy_url="http://policy.test",
            audit_url="http://audit.test",
            funding_url="http://funding.test",
            internal_token="secret-token",
            transport=httpx.MockTransport(handler),
        )

        self.assertTrue(adapter.account_readiness("u1")["ready"])
        self.assertIn("account_url", adapter.create_account_session("u1"))
        self.assertEqual(
            adapter.audit_summary("u1", limit=9)[0]["event"],
            "Wallet bound",
        )
        self.assertTrue(
            all(
                request.headers["authorization"]
                == "Bearer secret-token"
                for request in requests
            )
        )
        self.assertEqual(
            json.loads(requests[-2].content),
            {"user_id": "u1"},
        )
        self.assertEqual(requests[-1].url.params["user_id"], "u1")
        self.assertEqual(requests[-1].url.params["limit"], "9")

    def test_core_account_session_is_rewritten_to_node_public_url(self) -> None:
        adapter = CoreHttpAdapter(
            account_url="http://core.test:8019",
            action_url="http://action.test",
            policy_url="http://policy.test",
            audit_url="http://audit.test",
            funding_url="http://funding.test",
            internal_token="secret-token",
            public_base_url="https://node.example",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    201,
                    json={
                        "session_id": "session_1",
                        "account_url": (
                            "http://core.test:8019/account/session_1"
                        ),
                    },
                )
            ),
        )

        created = adapter.create_account_session("u1")

        self.assertEqual(
            created["account_url"],
            "https://node.example/account/session_1",
        )

    def test_core_account_proxy_forwards_only_public_account_route(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                303,
                headers=[
                    ("location", "/account"),
                    (
                        "set-cookie",
                        "clink_account_session=s1; Path=/account; Secure",
                    ),
                    (
                        "set-cookie",
                        "clink_account_csrf=c1; Path=/account; Secure",
                    ),
                ],
            )

        adapter = CoreHttpAdapter(
            account_url="http://core.test:8019",
            action_url="http://action.test",
            policy_url="http://policy.test",
            audit_url="http://audit.test",
            funding_url="http://funding.test",
            internal_token="secret-token",
            public_base_url="https://node.example",
            transport=httpx.MockTransport(handler),
        )

        response = adapter.proxy_account_request(
            method="POST",
            path="/account/session_1",
            query="source=telegram",
            headers=[
                ("content-type", "application/json"),
                ("cookie", "existing=value"),
                ("authorization", "Bearer browser-value"),
            ],
            body=b"{}",
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.header_values("set-cookie"),
            [
                "clink_account_session=s1; Path=/account; Secure",
                "clink_account_csrf=c1; Path=/account; Secure",
            ],
        )
        self.assertEqual(requests[0].url.path, "/account/session_1")
        self.assertEqual(requests[0].url.query, b"source=telegram")
        self.assertEqual(requests[0].headers["cookie"], "existing=value")
        self.assertNotIn("authorization", requests[0].headers)

        with self.assertRaises(ValueError):
            adapter.proxy_account_request(
                method="GET",
                path="/internal/account-readiness",
                query="",
                headers=[],
                body=b"",
            )

    def test_marketplace_and_prediction_expose_existing_capabilities(self) -> None:
        marketplace = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"status": "ok"})
            ),
        )
        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            account_binding_url="http://binding.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"status": "ok"})
            ),
        )

        marketplace_names = {
            item["name"] for item in marketplace.capabilities()
        }
        prediction_names = {
            item["name"] for item in prediction.capabilities()
        }

        self.assertIn("execute_clink_purchase", marketplace_names)
        self.assertIn(
            "execute_prediction_market_order_preview",
            prediction_names,
        )

    def test_prediction_defaults_to_managed_deposit_wallet_service(
        self,
    ) -> None:
        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            internal_token="secret-token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json={"status": "ok"})
            ),
        )

        self.assertEqual(
            prediction.deposit_wallet_url,
            "http://127.0.0.1:8048",
        )

    def test_marketplace_service_projection_is_display_only(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "offerings": [
                        {
                            "offering_id": "service_1",
                            "provider_id": "provider_risk",
                            "name": "Risk API",
                            "description": "Screen one address.",
                            "status": "registry_verified",
                            "tags": ["wallet-risk", "analytics"],
                            "endpoint": "https://private.example/check",
                            "input_schema": {"type": "object"},
                            "metadata": {
                                "trust_tier": "registry_verified",
                                "quality": {
                                    "l30DaysTotalCalls": 23,
                                },
                                "bazaar_targets": [
                                    {
                                        "name": "Nansen",
                                        "category": "data",
                                        "relationship": "first_party",
                                    }
                                ],
                            },
                            "payment_options": [
                                {
                                    "network": "eip155:8453",
                                    "price_usd": "0.010",
                                    "pay_to": "0x" + "9" * 40,
                                },
                                {
                                    "network": "eip155:137",
                                    "price_usd": "0.007",
                                    "pay_to": "0x" + "8" * 40,
                                },
                            ],
                        }
                    ],
                },
            )

        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="secret-token",
            transport=httpx.MockTransport(handler),
        )

        self.assertTrue(
            hasattr(adapter, "list_services"),
            "Marketplace adapter must expose a service catalog projection",
        )
        result = adapter.list_services(limit=20)

        self.assertEqual(
            result,
            {
                "count": 1,
                "services": [
                    {
                        "offering_id": "service_1",
                        "name": "Risk API",
                        "description": "Screen one address.",
                        "starting_price_usd": "0.007",
                        "networks": [
                            "eip155:137",
                            "eip155:8453",
                        ],
                        "trust_tier": "registry_verified",
                        "calls_30d": 23,
                        "category": "data",
                        "subcategory": "risk_identity",
                        "icon_key": "brand-nansen",
                        "icon_text": "RA",
                    }
                ],
            },
        )
        self.assertEqual(requests[0].url.path, "/catalog/search")
        self.assertEqual(
            json.loads(requests[0].content),
            {"query": "", "limit": 20},
        )
        self.assertEqual(
            requests[0].headers["authorization"],
            "Bearer secret-token",
        )
        serialized = json.dumps(result)
        for private_name in (
            "endpoint",
            "pay_to",
            "input_schema",
            "metadata",
        ):
            self.assertNotIn(private_name, serialized)

    def test_marketplace_service_projection_uses_safe_fallbacks(self) -> None:
        payload = {
            "count": 2,
            "offerings": [
                {
                    "offering_id": "service_unknown",
                    "provider_id": "provider_unknown",
                    "name": "Unknown Utility",
                    "description": "A utility without classification.",
                    "tags": ["not-a-real-category"],
                    "status": "verified",
                    "metadata": {
                        "icon_url": "https://tracker.example/icon.svg",
                        "bazaar_targets": [
                            {
                                "name": "../escape",
                                "category": "../../private",
                                "relationship": "first_party",
                            }
                        ],
                    },
                    "payment_options": [],
                },
                {
                    "offering_id": "service_search",
                    "provider_id": "provider_search",
                    "name": "Document Finder",
                    "description": "Find documents.",
                    "tags": ["semantic-search"],
                    "status": "verified",
                    "metadata": {},
                    "payment_options": [],
                },
            ],
        }

        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        )

        first = adapter.list_services()
        second = adapter.list_services()

        self.assertEqual(first["services"][0]["category"], "other")
        self.assertEqual(first["services"][0]["subcategory"], "other")
        self.assertRegex(
            first["services"][0]["icon_key"],
            r"^service-[a-f0-9]{12}$",
        )
        self.assertEqual(first["services"][0]["icon_text"], "UU")
        self.assertEqual(
            first["services"][0]["icon_key"],
            second["services"][0]["icon_key"],
        )
        self.assertEqual(first["services"][1]["category"], "search")
        self.assertEqual(
            first["services"][1]["subcategory"],
            "semantic_search",
        )
        self.assertNotIn("tracker.example", json.dumps(first))

    def test_verified_manifest_cannot_forge_registry_brand_identity(
        self,
    ) -> None:
        payload = {
            "count": 1,
            "offerings": [
                {
                    "offering_id": "service_voice",
                    "provider_id": "provider_merchant",
                    "name": "Merchant Voice Tool",
                    "description": "Convert text to speech.",
                    "tags": ["voice"],
                    "status": "verified",
                    "metadata": {
                        "bazaar_targets": [
                            {
                                "name": "Nansen",
                                "category": "data",
                                "relationship": "first_party",
                            }
                        ],
                    },
                    "payment_options": [],
                }
            ],
        }
        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        )

        service = adapter.list_services()["services"][0]

        self.assertEqual(service["category"], "inference")
        self.assertEqual(service["subcategory"], "voice_audio")
        self.assertRegex(service["icon_key"], r"^service-[a-f0-9]{12}$")
        self.assertNotEqual(service["icon_key"], "brand-nansen")

    def test_powered_by_marker_does_not_override_service_capability(
        self,
    ) -> None:
        payload = {
            "count": 1,
            "offerings": [
                {
                    "offering_id": "service_company_search",
                    "provider_id": "provider_enrich",
                    "name": "stable-enrich-company-search",
                    "description": (
                        "FullEnrich Company Search — by name, industry, "
                        "headcount, and headquarters."
                    ),
                    "tags": [],
                    "status": "registry_verified",
                    "metadata": {
                        "bazaar_targets": [
                            {
                                "name": "ElevenLabs",
                                "category": "inference",
                                "relationship": "powered_by",
                            }
                        ],
                    },
                    "payment_options": [],
                }
            ],
        }
        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        )

        service = adapter.list_services()["services"][0]

        self.assertEqual(service["category"], "search")
        self.assertEqual(service["subcategory"], "web_search")

    def test_native_brand_tag_corroborates_powered_by_category(self) -> None:
        payload = {
            "count": 1,
            "offerings": [
                {
                    "offering_id": "service_firecrawl_map",
                    "provider_id": "provider_vaaya",
                    "name": "Vaaya",
                    "description": (
                        "Firecrawl — Map all URLs on a website without "
                        "scraping content."
                    ),
                    "tags": ["firecrawl", "ai-agents", "pay-per-call"],
                    "status": "registry_verified",
                    "metadata": {
                        "bazaar_targets": [
                            {
                                "name": "Firecrawl",
                                "category": "search",
                                "relationship": "powered_by",
                            }
                        ],
                    },
                    "payment_options": [],
                }
            ],
        }
        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        )

        service = adapter.list_services()["services"][0]

        self.assertEqual(service["category"], "search")

    def test_subcategory_prefers_explicit_tags_to_incidental_mentions(
        self,
    ) -> None:
        payload = {
            "count": 1,
            "offerings": [
                {
                    "offering_id": "service_llm",
                    "provider_id": "provider_inference",
                    "name": "CheapTokens AI Inference",
                    "description": (
                        "OpenAI-compatible LLM inference and chat "
                        "completions with models, images, audio, and video."
                    ),
                    "tags": ["inference", "llm", "openai"],
                    "status": "registry_verified",
                    "metadata": {
                        "bazaar_targets": [
                            {
                                "name": "Venice",
                                "category": "inference",
                                "relationship": "powered_by",
                            }
                        ],
                    },
                    "payment_options": [],
                }
            ],
        }
        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=payload)
            ),
        )

        service = adapter.list_services()["services"][0]

        self.assertEqual(service["category"], "inference")
        self.assertEqual(service["subcategory"], "language_models")

    def test_business_public_proxies_are_restricted_to_signing_routes(
        self,
    ) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, text=request.url.path)

        transport = httpx.MockTransport(handler)
        marketplace = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=transport,
        )
        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            account_binding_url="http://binding.test",
            execution_url="http://execution.test",
            internal_token="token",
            public_base_url="https://node.test",
            live_operations_enabled=True,
            transport=transport,
        )

        checkout = marketplace.proxy_public_request(
            method="GET",
            path="/x402/checkout/purchase_1",
            query="",
            headers=[],
            body=b"",
        )
        asset = marketplace.proxy_public_request(
            method="GET",
            path="/assets/x402_checkout.js",
            query="",
            headers=[],
            body=b"",
        )
        binding = prediction.proxy_public_request(
            method="GET",
            path="/polymarket/binding-console/session_1",
            query="access_token=redacted",
            headers=[],
            body=b"",
        )
        order = prediction.proxy_public_request(
            method="GET",
            path="/execution/polymarket/order-signing-console/",
            query="",
            headers=[],
            body=b"",
        )
        order_asset = prediction.proxy_public_request(
            method="GET",
            path=(
                "/execution/polymarket/order-signing-assets/"
                "polymarket_order_signing.bundle.js"
            ),
            query="",
            headers=[],
            body=b"",
        )
        browser_headers = [
            ("authorization", "Bearer browser-capability"),
            ("x-clink-origin", "https://node.test"),
        ]
        order_session = prediction.proxy_public_request(
            method="GET",
            path="/execution/polymarket/browser-order-signing-session",
            query="",
            headers=browser_headers,
            body=b"",
        )
        order_status = prediction.proxy_public_request(
            method="GET",
            path=(
                "/execution/polymarket/"
                "browser-order-signing-session/status"
            ),
            query="",
            headers=browser_headers,
            body=b"",
        )
        order_complete = prediction.proxy_public_request(
            method="POST",
            path=(
                "/execution/polymarket/"
                "browser-order-signing-session/complete"
            ),
            query="",
            headers=[
                *browser_headers,
                ("content-type", "application/json"),
            ],
            body=(
                b'{"signed_order":{},"wallet_address":"0x1",'
                b'"order_type":"GTC"}'
            ),
        )

        self.assertEqual(checkout.status_code, 200)
        self.assertEqual(asset.status_code, 200)
        self.assertEqual(binding.status_code, 200)
        self.assertEqual(order.status_code, 200)
        self.assertEqual(order_asset.status_code, 200)
        self.assertEqual(order_session.status_code, 200)
        self.assertEqual(order_status.status_code, 200)
        self.assertEqual(order_complete.status_code, 200)
        self.assertEqual(requests[0].url.host, "market.test")
        self.assertEqual(requests[2].url.host, "binding.test")
        self.assertEqual(requests[3].url.host, "execution.test")
        for adapter, path in (
            (marketplace, "/merchant"),
            (marketplace, "/assets/admin.js"),
            (prediction, "/internal/polymarket/binding/x"),
            (prediction, "/execution/readiness"),
            (
                prediction,
                "/execution/polymarket/"
                "order-signing-sessions/session_1/complete",
            ),
        ):
            with self.assertRaises(ValueError):
                adapter.proxy_public_request(
                    method="GET",
                    path=path,
                    query="",
                    headers=[],
                    body=b"",
                )

    def test_prediction_reads_latest_binding_from_account_service(self) -> None:
        requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "binding_id": "pm_binding_1",
                    "status": "active",
                    "has_api_credentials": True,
                },
            )

        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            account_binding_url="http://binding.test",
            internal_token="secret-token",
            transport=httpx.MockTransport(handler),
        )

        status = prediction.account_status("telegram_jeff")

        self.assertEqual(status["binding_id"], "pm_binding_1")
        self.assertEqual(
            requests[0].url.path,
            "/internal/polymarket/bindings/latest/telegram_jeff",
        )
        self.assertEqual(
            requests[0].headers["authorization"],
            "Bearer secret-token",
        )

    def test_prediction_creates_subject_bound_binding_link_on_public_node(
        self,
    ) -> None:
        requests: list[httpx.Request] = []
        owner_wallet = "0x" + "A" * 40
        deposit_wallet = "0x" + "B" * 40

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            if request.url.path == "/polymarket/deposit-wallet/readiness":
                return httpx.Response(
                    200,
                    json={
                        "user_id": "telegram:101",
                        "owner_wallet": owner_wallet.lower(),
                        "deposit_wallet": deposit_wallet.lower(),
                        "status": "deployed",
                        "ready": True,
                        "can_use_x402": True,
                        "next_action": "fund_polymarket_deposit_wallet",
                    },
                )
            return httpx.Response(
                201,
                json={
                    "signing_url": (
                        "http://binding.test/polymarket/binding-console/"
                        "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
                    ),
                    "user_id": "telegram:101",
                },
            )

        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            account_binding_url="http://binding.test",
            deposit_wallet_url="http://deposit.test",
            internal_token="secret-token",
            public_base_url="https://www.agentonomy.xyz",
            transport=httpx.MockTransport(handler),
        )

        signing_url = prediction.create_binding_session(
            "telegram:101",
            wallet_address=owner_wallet,
        )

        self.assertEqual(
            signing_url,
            (
                "https://www.agentonomy.xyz/polymarket/binding-console/"
                "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
            ),
        )
        self.assertEqual(len(requests), 2)
        self.assertEqual(
            requests[0].url.path,
            "/polymarket/deposit-wallet/readiness",
        )
        self.assertEqual(
            requests[0].url.params["user_id"],
            "telegram:101",
        )
        self.assertEqual(
            requests[0].url.params["owner_wallet"],
            owner_wallet.lower(),
        )
        self.assertEqual(
            requests[1].url.path,
            "/internal/polymarket/binding-sessions",
        )
        self.assertEqual(
            requests[1].headers["authorization"],
            "Bearer secret-token",
        )
        self.assertEqual(
            json.loads(requests[1].content),
            {
                "user_id": "telegram:101",
                "agent_id": "hermes",
                "wallet_address": owner_wallet.lower(),
                "polymarket_deposit_wallet": deposit_wallet.lower(),
                "expires_in_minutes": 10,
                "return_url": "https://www.agentonomy.xyz/miniapp/",
                "metadata": {"source": "agentonomy_miniapp"},
            },
        )

    def test_prediction_accepts_binding_link_already_on_public_origin(
        self,
    ) -> None:
        public_url = (
            "https://www.agentonomy.xyz/polymarket/binding-console/"
            "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
        )
        owner_wallet = "0x" + "a" * 40
        deposit_wallet = "0x" + "b" * 40

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/polymarket/deposit-wallet/readiness":
                return httpx.Response(
                    200,
                    json={
                        "user_id": "telegram:101",
                        "owner_wallet": owner_wallet,
                        "deposit_wallet": deposit_wallet,
                        "status": "deployed",
                        "ready": True,
                        "can_use_x402": True,
                        "next_action": "fund_polymarket_deposit_wallet",
                    },
                )
            return httpx.Response(
                201,
                json={"signing_url": public_url},
            )

        prediction = PredictionMarketsHttpAdapter(
            base_url="http://prediction.test",
            account_binding_url="http://binding.test",
            deposit_wallet_url="http://deposit.test",
            internal_token="secret-token",
            public_base_url="https://www.agentonomy.xyz",
            transport=httpx.MockTransport(handler),
        )

        self.assertEqual(
            prediction.create_binding_session(
                "telegram:101",
                wallet_address=owner_wallet,
            ),
            public_url,
        )

    def test_prediction_rejects_untrusted_deposit_wallet_readiness(
        self,
    ) -> None:
        owner_wallet = "0x" + "a" * 40
        deposit_wallet = "0x" + "b" * 40
        cases = (
            ("user_id", "telegram:202"),
            ("owner_wallet", "0x" + "c" * 40),
            ("ready", False),
            ("can_use_x402", False),
            ("deposit_wallet", None),
            ("deposit_wallet", "0x" + "0" * 40),
        )

        for field, value in cases:
            with self.subTest(field=field, value=value):
                requests: list[httpx.Request] = []
                readiness = {
                    "user_id": "telegram:101",
                    "owner_wallet": owner_wallet,
                    "deposit_wallet": deposit_wallet,
                    "status": "deployed",
                    "ready": True,
                    "can_use_x402": True,
                    "next_action": "fund_polymarket_deposit_wallet",
                }
                readiness[field] = value

                def handler(request: httpx.Request) -> httpx.Response:
                    requests.append(request)
                    if (
                        request.url.path
                        == "/polymarket/deposit-wallet/readiness"
                    ):
                        return httpx.Response(200, json=readiness)
                    return httpx.Response(
                        201,
                        json={
                            "signing_url": (
                                "http://binding.test/polymarket/"
                                "binding-console/"
                                "pm_bind_sess_a1b2c3d4e5f6"
                                "?access_token=console-secret"
                            )
                        },
                    )

                prediction = PredictionMarketsHttpAdapter(
                    base_url="http://prediction.test",
                    account_binding_url="http://binding.test",
                    deposit_wallet_url="http://deposit.test",
                    internal_token="secret-token",
                    public_base_url="https://www.agentonomy.xyz",
                    transport=httpx.MockTransport(handler),
                )

                try:
                    prediction.create_binding_session(
                        "telegram:101",
                        wallet_address=owner_wallet,
                    )
                except DownstreamError:
                    pass
                except Exception as exc:
                    self.fail(
                        "deposit readiness validation leaked "
                        f"{type(exc).__name__}"
                    )
                else:
                    self.fail("untrusted deposit readiness was accepted")

                self.assertEqual(len(requests), 1)
                self.assertEqual(
                    requests[0].url.path,
                    "/polymarket/deposit-wallet/readiness",
                )

    def test_prediction_binding_link_rejects_untrusted_backend_urls(self) -> None:
        owner_wallet = "0x" + "a" * 40
        deposit_wallet = "0x" + "b" * 40
        valid_path = (
            "/polymarket/binding-console/"
            "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
        )
        unsafe_urls = (
            "https://attacker.invalid/polymarket/binding-console/pm_bind_sess_a1",
            f"https://attacker.invalid{valid_path}",
            f"https://www.agentonomy.xyz.evil{valid_path}",
            f"https://www.agentonomy.xyz:444{valid_path}",
            f"https://user@www.agentonomy.xyz{valid_path}",
            f"http://binding.test:81{valid_path}",
            "http://binding.test/admin/pm_bind_sess_a1",
            "http://binding.test/polymarket/binding-console/../admin",
            "http://user@binding.test/polymarket/binding-console/pm_bind_sess_a1",
            "http://binding.test/polymarket/binding-console/not-a-session",
            123,
            None,
        )

        for signing_url in unsafe_urls:
            with self.subTest(signing_url=signing_url):
                def handler(
                    request: httpx.Request,
                    value=signing_url,
                ) -> httpx.Response:
                    if (
                        request.url.path
                        == "/polymarket/deposit-wallet/readiness"
                    ):
                        return httpx.Response(
                            200,
                            json={
                                "user_id": "telegram:101",
                                "owner_wallet": owner_wallet,
                                "deposit_wallet": deposit_wallet,
                                "status": "deployed",
                                "ready": True,
                                "can_use_x402": True,
                                "next_action": (
                                    "fund_polymarket_deposit_wallet"
                                ),
                            },
                        )
                    return httpx.Response(
                        201,
                        json={"signing_url": value},
                    )

                prediction = PredictionMarketsHttpAdapter(
                    base_url="http://prediction.test",
                    account_binding_url="http://binding.test",
                    deposit_wallet_url="http://deposit.test",
                    internal_token="secret-token",
                    public_base_url="https://www.agentonomy.xyz",
                    transport=httpx.MockTransport(handler),
                )

                with self.assertRaises(DownstreamError) as caught:
                    prediction.create_binding_session(
                        "telegram:101",
                        wallet_address=owner_wallet,
                    )

                self.assertEqual(
                    caught.exception.detail,
                    "binding signing URL was invalid",
                )

    def test_object_request_rejects_json_list_root(self) -> None:
        adapter = MarketplaceHttpAdapter(
            base_url="http://market.test",
            internal_token="token",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, json=[])
            ),
        )

        with self.assertRaises(DownstreamError) as caught:
            adapter.health()

        self.assertEqual(
            caught.exception.detail,
            "response root must be an object",
        )

    def test_downstream_errors_are_structured_and_not_retried(self) -> None:
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(
                503,
                json={"detail": "funding unavailable"},
            )

        adapter = CoreHttpAdapter(
            account_url="http://core.test",
            action_url="http://action.test",
            policy_url="http://policy.test",
            audit_url="http://audit.test",
            funding_url="http://funding.test",
            internal_token="secret-token",
            transport=httpx.MockTransport(handler),
        )

        with self.assertRaises(DownstreamError) as caught:
            adapter.account_readiness("u1")

        self.assertEqual(calls, 1)
        self.assertEqual(caught.exception.status_code, 503)
        self.assertEqual(caught.exception.detail, "funding unavailable")


if __name__ == "__main__":
    unittest.main()
