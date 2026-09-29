from __future__ import annotations

import unittest

from mcp import types

from apps.node.clink_node.api import NodeApiContext
from apps.node.clink_node.config import NodeSettings, Profile
from apps.node.clink_node.mcp_gateway import build_native_tools
from apps.node.clink_node.mcp_proxy import (
    DownstreamMcpFailure,
    McpToolProxy,
)
from apps.node.clink_node.paths import NodePaths


class NativeCore:
    def wallet_balances(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "status": "ready",
            "wallet_bound": True,
            "wallet_address": "0x1111111111111111111111111111111111111111",
            "balances": {
                "eip155:137": {
                    "status": "ready",
                    "asset": "USDC",
                    "amount_atomic": "5000000",
                    "amount_usdc": "5.000000",
                }
            },
        }

    def account_readiness(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "wallet_bound": True,
            "wallet_address": "0x1111111111111111111111111111111111111111",
            "spending_grant_active": True,
            "active_spending_mandate": {
                "limits_usdc": {"total": "25"},
                "remaining_usdc": {"total": "23"},
                "product_scopes": [
                    "marketplace",
                    "prediction_markets",
                ]
            },
            "chain_allowances": {},
            "ready": True,
        }

    def create_account_session(self, user_id: str) -> dict:
        return {"user_id": user_id, "account_url": "http://account.test"}

    def audit_summary(self, user_id: str, limit: int) -> list[dict]:
        return [{"event": "Wallet bound", "summary": user_id, "at": "now"}]


class NativeBusiness:
    def __init__(self, name: str) -> None:
        self.name = name

    def capabilities(self) -> list[dict]:
        return []

    def health(self) -> dict:
        return {"status": "ok"}


class NativePrediction(NativeBusiness):
    def account_balance(self, user_id: str) -> dict:
        return {
            "status": "ready",
            "user_id": user_id,
            "venue": "polymarket",
            "venue_wallet_address": "0x2222222222222222222222222222222222222222",
            "asset": "USDC",
            "available_amount_atomic": "2000000",
            "available_amount_usdc": "2.000000",
        }

    def account_status(self, user_id: str) -> dict:
        return {
            "user_id": user_id,
            "status": "active",
            "wallet_address": "0x1111111111111111111111111111111111111111",
            "has_api_credentials": True,
        }


class NativeRepository:
    def list_modules(self) -> list:
        return []


class FakeMcpClient:
    def __init__(
        self,
        tools: list[types.Tool],
        result: types.CallToolResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.tools = tools
        self.result = result or types.CallToolResult(
            content=[types.TextContent(type="text", text="ok")],
            structuredContent={"status": "ok"},
        )
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def list_tools(self) -> list[types.Tool]:
        return self.tools

    async def call_tool(
        self,
        name: str,
        arguments: dict,
    ) -> types.CallToolResult:
        self.calls.append((name, arguments))
        if self.error:
            raise self.error
        return self.result


def tool(name: str) -> types.Tool:
    return types.Tool(
        name=name,
        description=f"{name} description",
        inputSchema={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    )


class McpGatewayTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_account_and_activity_tools_use_node_projection(
        self,
    ) -> None:
        settings = NodeSettings.defaults(
            Profile.PERSONAL,
            paths=NodePaths.from_home(
                __import__("pathlib").Path("/tmp/clink-native-test")
            ),
        )
        context = NodeApiContext(
            settings=settings,
            repository=NativeRepository(),
            interaction_service=None,
            session_token="token",
            core=NativeCore(),
            marketplace=NativeBusiness("marketplace"),
            prediction_markets=NativePrediction("prediction-markets"),
        )
        native = build_native_tools(context)

        account = await native[
            "get_clink_account_readiness"
        ].handler({"user_id": "telegram_jeff"})
        activity = await native[
            "get_clink_activity"
        ].handler({"user_id": "telegram_jeff", "limit": 5})
        balances = await native[
            "get_clink_balances"
        ].handler({"user_id": "telegram_jeff"})

        self.assertEqual(account["status"], "ready")
        self.assertTrue(account["products"]["prediction_markets"]["ready"])
        self.assertEqual(activity["count"], 1)
        self.assertEqual(balances["status"], "ready")
        self.assertEqual(
            balances["wallet_funds"]["balances"]["eip155:137"]["amount_usdc"],
            "5.000000",
        )
        self.assertEqual(
            balances["polymarket_funds"]["available_amount_usdc"],
            "2.000000",
        )
        self.assertEqual(
            balances["agent_spending_authorization"]["remaining_usdc"]["total"],
            "23",
        )
        self.assertEqual(
            balances["agent_spending_authorization"]["meaning"],
            "authorization_budget_not_wallet_balance",
        )

    async def test_lists_node_and_downstream_tools_without_renaming(self) -> None:
        marketplace = FakeMcpClient([tool("search_clink_services")])
        prediction = FakeMcpClient([tool("search_prediction_markets")])
        proxy = McpToolProxy(
            {
                "marketplace": marketplace,
                "prediction-markets": prediction,
            }
        )

        tools = await proxy.list_tools()
        names = {item.name for item in tools}

        self.assertIn("clink_node_status", names)
        self.assertIn("create_core_account_setup_link", names)
        self.assertIn("search_clink_services", names)
        self.assertIn("search_prediction_markets", names)

    async def test_routes_tool_call_to_owning_module_once(self) -> None:
        marketplace = FakeMcpClient([tool("execute_clink_purchase")])
        prediction = FakeMcpClient([tool("search_prediction_markets")])
        proxy = McpToolProxy(
            {
                "marketplace": marketplace,
                "prediction-markets": prediction,
            }
        )
        await proxy.list_tools()

        result = await proxy.call_tool(
            "execute_clink_purchase",
            {"preview_id": "preview_1"},
        )

        self.assertEqual(result.structuredContent, {"status": "ok"})
        self.assertEqual(
            marketplace.calls,
            [("execute_clink_purchase", {"preview_id": "preview_1"})],
        )
        self.assertEqual(prediction.calls, [])

    async def test_rejects_downstream_tool_name_collisions(self) -> None:
        proxy = McpToolProxy(
            {
                "marketplace": FakeMcpClient([tool("duplicate")]),
                "prediction-markets": FakeMcpClient([tool("duplicate")]),
            }
        )

        with self.assertRaises(ValueError):
            await proxy.list_tools()

    async def test_node_native_tool_replaces_legacy_downstream_duplicate(
        self,
    ) -> None:
        prediction = FakeMcpClient(
            [tool("create_core_account_setup_link")]
        )
        proxy = McpToolProxy({"prediction-markets": prediction})

        tools = await proxy.list_tools()
        matches = [
            item
            for item in tools
            if item.name == "create_core_account_setup_link"
        ]

        self.assertEqual(len(matches), 1)
        result = await proxy.call_tool(
            "create_core_account_setup_link",
            {"user_id": "telegram_jeff"},
        )
        self.assertEqual(result["status"], "not_configured")
        self.assertEqual(prediction.calls, [])

    async def test_failure_is_structured_and_not_retried(self) -> None:
        marketplace = FakeMcpClient(
            [tool("execute_clink_purchase")],
            error=TimeoutError("merchant timeout"),
        )
        proxy = McpToolProxy({"marketplace": marketplace})
        await proxy.list_tools()

        with self.assertRaises(DownstreamMcpFailure) as caught:
            await proxy.call_tool(
                "execute_clink_purchase",
                {"preview_id": "preview_1"},
            )

        self.assertEqual(len(marketplace.calls), 1)
        self.assertFalse(caught.exception.retry_safe)
        self.assertEqual(caught.exception.module, "marketplace")


if __name__ == "__main__":
    unittest.main()
