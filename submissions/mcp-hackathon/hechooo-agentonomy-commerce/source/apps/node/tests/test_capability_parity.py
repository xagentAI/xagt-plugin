from __future__ import annotations

import ast
import unittest
from pathlib import Path

from apps.node.clink_node.adapters.marketplace import (
    MARKETPLACE_CAPABILITIES,
)
from apps.node.clink_node.adapters.prediction_markets import (
    PREDICTION_MARKET_CAPABILITIES,
)


ROOT = Path(__file__).resolve().parents[3]


def _decorated_mcp_tools(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
            ):
                names.append(node.name)
                break
    return tuple(names)


class CapabilityParityTests(unittest.TestCase):
    def test_marketplace_public_surface_is_preserved(self) -> None:
        actual = _decorated_mcp_tools(
            ROOT / "apps/marketplace/mcp_servers/marketplace_server.py"
        )

        self.assertEqual(actual, MARKETPLACE_CAPABILITIES)
        self.assertEqual(len(actual), 7)

    def test_prediction_markets_hides_obsolete_funding_ui_capability(self) -> None:
        actual = _decorated_mcp_tools(
            ROOT
            / "apps/prediction-markets/mcp_servers/"
            "prediction_markets_server.py"
        )

        self.assertNotIn("prepare_polymarket_funding_ui", actual)
        self.assertEqual(PREDICTION_MARKET_CAPABILITIES, actual)
        self.assertEqual(len(actual), len(set(actual)))
        self.assertEqual(
            len(PREDICTION_MARKET_CAPABILITIES),
            len(set(PREDICTION_MARKET_CAPABILITIES)),
        )
        self.assertEqual(len(actual), 29)
        self.assertEqual(len(PREDICTION_MARKET_CAPABILITIES), 29)
        self.assertNotIn(
            "prepare_polymarket_funding_ui",
            PREDICTION_MARKET_CAPABILITIES,
        )

    def test_money_moving_tools_remain_in_the_snapshot(self) -> None:
        self.assertIn(
            "execute_clink_purchase",
            MARKETPLACE_CAPABILITIES,
        )
        self.assertIn(
            "fund_polymarket_from_spending_authorization",
            PREDICTION_MARKET_CAPABILITIES,
        )
        self.assertIn(
            "execute_prediction_market_order_preview",
            PREDICTION_MARKET_CAPABILITIES,
        )


if __name__ == "__main__":
    unittest.main()
