import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.preview_service.service import CoreGateway, PreviewService
from shared.schemas import CreateOrderPreviewRequest, UnifiedMarket


class FakeCoreGateway(CoreGateway):
    def create_action_intent(self, payload: dict) -> dict:
        assert payload["action_type"] == "prediction_market_order_preview"
        assert payload["merchant_id"] == "polymarket"
        return {"action_id": "act_fake", "state": "created"}

    def evaluate_policy(self, payload: dict) -> dict:
        assert payload["action_id"] == "act_fake"
        assert payload["requires_confirmation"] is True
        return {
            "policy_decision_id": "policy_fake",
            "action_id": "act_fake",
            "approved": False,
            "decision": "needs_confirmation",
            "required_action": "request_user_confirmation",
            "reasons": ["preview requires user confirmation"],
        }

    def write_audit_event(self, payload: dict) -> dict:
        assert payload["action_id"] == "act_fake"
        return {"event_id": f"audit_{payload['event_type']}", **payload}


def main() -> None:
    storage = Path("/tmp/clink_prediction_preview_test.jsonl")
    storage.unlink(missing_ok=True)
    service = PreviewService(storage_file=storage, core_gateway=FakeCoreGateway())
    market = UnifiedMarket(
        platform="polymarket",
        market_id="691547",
        title="Kraken IPO by December 31, 2026?",
        yes_price=0.375,
        no_price=0.625,
        liquidity_usd=4367.10,
        tradable=True,
        execution_ready=True,
    )
    preview = service.create_order_preview(
        CreateOrderPreviewRequest(
            user_id="demo-user",
            agent_id="hermes_agent",
            market=market,
            outcome="Yes",
            side="buy",
            amount_usd="1",
        )
    )
    assert preview.preview_id.startswith("pm_preview_")
    assert preview.platform == "polymarket"
    assert preview.limit_price == 0.375
    assert preview.estimated_contracts > 2.6
    assert preview.state == "confirmation_required"
    assert preview.next_action == "request_user_confirmation"
    assert preview.core_action_id == "act_fake"
    assert preview.core_policy_decision_id == "policy_fake"
    assert preview.core_audit_event_ids

    loaded = service.get_order_preview(preview.preview_id)
    assert loaded is not None
    assert loaded.preview_id == preview.preview_id

    below_venue_minimum_market = market.model_copy(
        update={
            "market_id": "venue-minimum-market",
            "raw": {"orderMinSize": "5"},
        }
    )
    below_venue_minimum = service.create_order_preview(
        CreateOrderPreviewRequest(
            user_id="demo-user",
            agent_id="hermes_agent",
            market=below_venue_minimum_market,
            outcome="Yes",
            side="buy",
            amount_usd="1",
        )
    )
    assert below_venue_minimum.state == "confirmation_required"
    assert below_venue_minimum.next_action == "request_user_confirmation"
    assert below_venue_minimum.metadata["venue_minimum_order_usd"] == "5"
    assert below_venue_minimum.metadata["venue_minimum_order_warning"]

    blocked_market = market.model_copy(update={"market_id": "closed-market", "tradable": False})
    try:
        service.create_order_preview(
            CreateOrderPreviewRequest(
                user_id="demo-user",
                agent_id="hermes_agent",
                market=blocked_market,
                outcome="Yes",
                side="buy",
                amount_usd="1",
            )
        )
    except ValueError as exc:
        assert "market must be tradable" in str(exc)
    else:
        raise AssertionError("non-tradable market should not create an order preview")

    print(json.dumps({"status": "ok", "preview_id": preview.preview_id, "state": preview.state}, indent=2))


if __name__ == "__main__":
    main()
