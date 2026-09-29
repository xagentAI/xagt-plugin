from __future__ import annotations

import unittest
from unittest.mock import patch

from mcp_servers import marketplace_server
from scripts.public_mcp_surface_smoke import (
    EXPECTED_TOOL_NAMES,
    health_result_is_degraded,
)


class MarketplaceMcpSurfaceTests(unittest.TestCase):
    OPC_INSTALLATION_ID = "opc_" + "a" * 40

    def test_public_smoke_requires_the_complete_agent_commerce_surface(self) -> None:
        self.assertEqual(
            EXPECTED_TOOL_NAMES,
            {
                "search_clink_services",
                "get_clink_service_details",
                "compare_clink_service_quotes",
                "create_clink_purchase_preview",
                "execute_clink_purchase",
                "get_clink_purchase",
                "clink_marketplace_health",
            },
        )

    def test_degraded_health_is_not_a_transport_failure(self) -> None:
        self.assertTrue(
            health_result_is_degraded(
                is_error=True,
                texts=[
                    "Clink Marketplace registry returned HTTP 503: "
                    '{"status":"degraded","worker":{"status":"stale"}}'
                ],
            )
        )
        self.assertFalse(
            health_result_is_degraded(
                is_error=True,
                texts=["Clink Marketplace registry request failed: connection refused"],
            )
        )

    def test_search_forwards_read_only_filters(self) -> None:
        expected = {"query": "wallet risk", "count": 0, "offerings": []}
        with patch.object(marketplace_server, "_request_json", return_value=expected) as request:
            result = marketplace_server.search_clink_services(
                "wallet risk",
                network="eip155:137",
                max_price_usd="0.05",
                limit=12,
            )

        self.assertEqual(result, expected)
        request.assert_called_once_with(
            f"{marketplace_server.CONFIG.registry_url}/catalog/search",
            {
                "query": "wallet risk",
                "network": "eip155:137",
                "max_price_usd": "0.05",
                "limit": 12,
            },
        )

    def test_details_and_health_are_get_requests(self) -> None:
        with patch.object(
            marketplace_server,
            "_request_json",
            side_effect=[{"offering": {"offering_id": "off_1"}}, {"status": "ok"}],
        ) as request:
            details = marketplace_server.get_clink_service_details("off_1")
            health = marketplace_server.clink_marketplace_health()

        self.assertEqual(details["offering"]["offering_id"], "off_1")
        self.assertEqual(health["status"], "ok")
        self.assertEqual(
            request.call_args_list[0].args,
            (f"{marketplace_server.CONFIG.registry_url}/catalog/offerings/off_1",),
        )
        self.assertEqual(
            request.call_args_list[1].args,
            (f"{marketplace_server.CONFIG.registry_url}/healthz",),
        )

    def test_execute_purchase_preserves_transient_result_contract(self) -> None:
        expected = {
            "purchase": {"purchase_id": "purchase_1", "state": "delivered"},
            "service_result": {"risk": "low"},
        }
        with patch.object(
            marketplace_server, "_request_json", return_value=expected
        ) as request:
            result = marketplace_server.execute_clink_purchase(
                "preview/unsafe",
                user_confirmed=True,
                spending_authorization_id="auth_1",
                transaction_hash="0xabc",
                payment_response={"signature": "0xsigned"},
            )

        self.assertEqual(result, expected)
        request.assert_called_once_with(
            f"{marketplace_server.CONFIG.registry_url}/purchases/preview%2Funsafe/execute",
            {
                "user_confirmed": True,
                "spending_authorization_id": "auth_1",
                "transaction_hash": "0xabc",
                "payment_response": {"signature": "0xsigned"},
            },
        )

    def test_opc_installation_is_forwarded_for_preview_and_execute(self) -> None:
        with patch.object(
            marketplace_server,
            "_request_json",
            side_effect=[{"preview_id": "preview_1"}, {"purchase_id": "purchase_1"}],
        ) as request:
            marketplace_server.create_clink_purchase_preview(
                "user_1",
                "offering_1",
                {"query": "coffee"},
                opc_installation_id=self.OPC_INSTALLATION_ID,
            )
            marketplace_server.execute_clink_purchase(
                "preview_1",
                user_confirmed=True,
                opc_installation_id=self.OPC_INSTALLATION_ID,
            )

        self.assertEqual(
            request.call_args_list[0].args[1]["opc_installation_id"],
            self.OPC_INSTALLATION_ID,
        )
        self.assertEqual(
            request.call_args_list[1].args[1]["opc_installation_id"],
            self.OPC_INSTALLATION_ID,
        )


if __name__ == "__main__":
    unittest.main()
