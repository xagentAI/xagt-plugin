from __future__ import annotations

import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.node.clink_node.companion import attach_companion


class CompanionTests(unittest.TestCase):
    def setUp(self) -> None:
        app = FastAPI()
        attach_companion(app, miniapp_enabled=True)
        self.client = TestClient(app)

    def test_disabled_miniapp_hides_shell_and_dedicated_assets(self) -> None:
        app = FastAPI()
        attach_companion(app, miniapp_enabled=False)
        client = TestClient(app)

        self.assertEqual(client.get("/miniapp/").status_code, 404)
        for path in (
            "/static/miniapp.html",
            "/static//miniapp.css",
            "/static/%2e/miniapp.js",
            "/static/miniapp.html/",
            "/static/nested/miniapp.css",
            "/static/nested/%2e%2e/miniapp.js",
        ):
            with self.subTest(path=path):
                response = client.get(path, follow_redirects=False)
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("location", response.headers)
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/static/app.js").status_code, 200)
        self.assertEqual(client.get("/static/styles.css").status_code, 200)

    def test_companion_prioritizes_read_only_marketplace_showcase(
        self,
    ) -> None:
        page = self.client.get("/").text
        script = self.client.get("/static/landing.js").text

        self.assertIn("THE CONTROL LAYER FOR AGENTIC COMMERCE", page)
        self.assertIn("Let agents act.", page)
        self.assertIn("Keep control of the money.", page)
        self.assertIn('href="/static/landing.css"', page)
        self.assertIn('src="/static/landing.js"', page)
        self.assertIn('id="marketplace-showcase"', page)
        self.assertIn('id="marketplace-services"', page)
        self.assertLess(
            page.index('id="control-flow"'),
            page.index('id="marketplace-showcase"'),
        )
        self.assertIn("/v1/marketplace/services?limit=20", script)
        self.assertIn("renderMarketplace", script)
        self.assertNotIn('id="account-selector"', page)
        self.assertNotIn("innerHTML", script)

    def test_marketplace_cards_do_not_add_transaction_controls(
        self,
    ) -> None:
        page = self.client.get("/").text
        script = self.client.get("/static/landing.js").text

        self.assertNotIn("Buy service", page)
        self.assertNotIn("Get quote", page)
        self.assertNotIn("create_clink_purchase_preview", script)
        self.assertNotIn("execute_clink_purchase", script)
        self.assertIn(
            "Marketplace service catalog temporarily unavailable.",
            script,
        )
        self.assertIn(
            "No usable services are available right now.",
            script,
        )

    def test_marketplace_groups_services_and_renders_icons(self) -> None:
        page = self.client.get("/").text
        script = self.client.get("/static/landing.js").text
        styles = self.client.get("/static/landing.css").text

        self.assertIn("const CATEGORY_ORDER", script)
        self.assertIn('class="service-catalog"', page)
        self.assertIn(
            'class="service-grid marketplace-skeleton-grid"',
            page,
        )
        self.assertIn("function serviceGroup(category, services)", script)
        self.assertIn("function serviceIcon(service)", script)
        self.assertIn('className = "service-category"', script)
        self.assertIn('className = "service-icon"', script)
        self.assertIn("service.subcategory", script)
        self.assertIn("grouped.get(category)", script)
        self.assertIn("formatPrice", script)
        self.assertNotIn("innerHTML", script)
        self.assertIn(".service-category-header", styles)
        self.assertIn(".service-card-header", styles)
        self.assertIn(".service-icon", styles)
        self.assertIn(".service-subcategory", styles)
        self.assertIn(".tone-0", styles)

    def test_marketplace_icons_do_not_hotlink_remote_assets(self) -> None:
        script = self.client.get("/static/landing.js").text

        self.assertIn("service.icon_key", script)
        self.assertIn("service.icon_text", script)
        self.assertNotIn("service.icon_url", script)
        self.assertNotIn("metadata.icon", script)

    def test_marketplace_facts_wrap_instead_of_hiding_values(self) -> None:
        styles = self.client.get("/static/landing.css").text
        script = self.client.get("/static/landing.js").text
        fact_rule = styles.split(
            ".service-facts strong {",
            1,
        )[1].split("}", 1)[0]

        self.assertIn("overflow-wrap: anywhere", fact_rule)
        self.assertNotIn("overflow: hidden", fact_rule)
        self.assertNotIn("text-overflow: ellipsis", fact_rule)
        self.assertIn("function trustLabel(value)", script)
        self.assertIn('replaceAll("_", " ")', script)

    def test_wallet_binding_is_delegated_to_the_secure_core_account(self) -> None:
        response = self.client.get("/console")

        self.assertIn('class="account-handoff"', response.text)
        self.assertIn("Open the account link created", response.text)
        self.assertNotIn("Choose the exact wallet to bind", response.text)
        self.assertNotIn('id="wallet-options"', response.text)
        self.assertNotIn('id="browser-wallet-state"', response.text)

    def test_companion_script_has_no_wallet_request_surface(self) -> None:
        script = self.client.get("/static/landing.js").text

        for wallet_api in (
            "eip6963:",
            "eth_requestAccounts",
            "eth_accounts",
            "eth_chainId",
            "personal_sign",
            "eth_signTypedData_v4",
            "wallet_switchEthereumChain",
            "eth_sendTransaction",
            "provider.request",
            "window.clinkWallet",
        ):
            self.assertNotIn(wallet_api, script)
        self.assertNotIn("/v1/account/summary", script)
        self.assertNotIn("/v1/activity", script)

    def test_agentonomy_console_is_a_separate_public_surface(self) -> None:
        home = self.client.get("/")
        console = self.client.get("/console")
        console_slash = self.client.get("/console/")

        self.assertEqual(home.status_code, 200)
        self.assertEqual(console.status_code, 200)
        self.assertEqual(console_slash.status_code, 200)
        self.assertNotIn('id="account-user-id"', home.text)
        self.assertIn("Agentonomy Console", console.text)
        self.assertIn('id="account-user-id"', console.text)
        self.assertIn('id="activity-rows"', console.text)
        self.assertIn('href="/static/console.css"', console.text)
        self.assertIn('src="/static/console.js"', console.text)
        self.assertEqual(console.headers["cache-control"], "no-store")
        self.assertEqual(console.headers["referrer-policy"], "no-referrer")
        self.assertEqual(
            console.headers["x-content-type-options"],
            "nosniff",
        )

    def test_public_surfaces_share_the_local_agentonomy_mark(self) -> None:
        home = self.client.get("/").text
        console = self.client.get("/console").text
        mark = self.client.get("/static/agentonomy-mark.png")

        self.assertEqual(mark.status_code, 200)
        self.assertEqual(mark.headers["content-type"], "image/png")
        for page in (home, console):
            self.assertIn(
                'rel="icon" href="/static/agentonomy-mark.png"',
                page,
            )
            self.assertIn(
                'src="/static/agentonomy-mark.png"',
                page,
            )

    def test_browser_delivered_node_assets_do_not_name_hermes(self) -> None:
        for path in (
            "/",
            "/console",
            "/miniapp/",
            "/static/landing.css",
            "/static/landing.js",
            "/static/console.css",
            "/static/console.js",
            "/static/miniapp.css",
            "/static/miniapp.js",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn("hermes", response.text.lower())

    def test_interaction_route_uses_fragment_token_client_side(self) -> None:
        response = self.client.get("/interactions/int_example")

        self.assertEqual(response.status_code, 200)
        self.assertIn("data-interaction-id=\"int_example\"", response.text)
        self.assertIn("The access token stays in this browser", response.text)

    def test_companion_loads_unified_account_and_activity_projections(
        self,
    ) -> None:
        page = self.client.get("/console").text
        script = self.client.get("/static/console.js").text

        self.assertIn('id="account-user-id"', page)
        self.assertIn('id="refresh-account"', page)
        self.assertIn('id="activity-rows"', page)
        self.assertIn("/v1/account/summary", script)
        self.assertIn("/v1/activity", script)
        self.assertIn("URLSearchParams(location.search)", script)
        self.assertIn("textContent", script)

    def test_miniapp_serves_an_isolated_same_origin_chat_shell(self) -> None:
        response = self.client.get("/miniapp/")

        telegram_sdk = (
            'src="https://telegram.org/js/telegram-web-app.js?63"'
        )
        local_script = 'src="/static/miniapp.js"'
        expected_csp = (
            "default-src 'self'; "
            "script-src 'self' https://telegram.org; "
            "connect-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "object-src 'none'; "
            "base-uri 'none'; "
            "form-action 'self'"
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="miniapp-transcript"', response.text)
        self.assertIn('id="miniapp-composer"', response.text)
        self.assertIn('id="miniapp-operations"', response.text)
        self.assertIn('href="/static/miniapp.css"', response.text)
        self.assertIn(telegram_sdk, response.text)
        self.assertIn(local_script, response.text)
        self.assertEqual(response.text.count(telegram_sdk), 1)
        self.assertEqual(
            response.text.index("<script"),
            response.text.index(f"<script {telegram_sdk}"),
        )
        self.assertLess(
            response.text.index(telegram_sdk),
            response.text.index(local_script),
        )
        self.assertLess(
            response.text.index(telegram_sdk),
            response.text.index("</head>"),
        )
        self.assertNotIn("<script>", response.text)
        self.assertNotIn("style=", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertEqual(
            response.headers["x-content-type-options"],
            "nosniff",
        )
        self.assertEqual(
            response.headers["content-security-policy"],
            expected_csp,
        )

        styles = self.client.get("/static/miniapp.css")
        script = self.client.get("/static/miniapp.js")
        self.assertEqual(styles.status_code, 200)
        self.assertEqual(script.status_code, 200)
        self.assertIn("--tg-theme-bg-color", styles.text)
        self.assertIn("prefers-reduced-motion", styles.text)
        self.assertIn("Telegram?.WebApp", script.text)
        self.assertNotIn("initDataUnsafe", script.text)
        self.assertNotIn("innerHTML", script.text)
        self.assertNotIn("hermes", response.text.lower())
        self.assertNotIn("hermes", script.text.lower())

    def test_miniapp_does_not_regress_existing_companion_routes(self) -> None:
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(
            self.client.get("/interactions/int_example").status_code,
            200,
        )
        self.assertEqual(self.client.get("/static/app.js").status_code, 200)


if __name__ == "__main__":
    unittest.main()
