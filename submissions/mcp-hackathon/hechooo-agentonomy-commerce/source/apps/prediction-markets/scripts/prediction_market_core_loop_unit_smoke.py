import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from platforms.base import ExecutionAdapter, PlatformExecutionResult  # noqa: E402
from services.execution_service.service import ExecutionService  # noqa: E402
from services.preview_service.service import CoreGateway, PreviewService  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.schemas import CreateOrderPreviewRequest, ExecutePredictionMarketOrderRequest, PredictionMarketOrderPreview, UnifiedMarket  # noqa: E402


class RecordingCoreGateway(CoreGateway):
    def __init__(self) -> None:
        self.action_types: list[str] = []
        self.audit_types: list[str] = []

    def create_action_intent(self, payload: dict) -> dict:
        self.action_types.append(payload["action_type"])
        return {"action_id": f"act_{payload['action_type']}", **payload}

    def evaluate_policy(self, payload: dict) -> dict:
        action_type = payload["action_type"]
        if action_type == "prediction_market_order_preview":
            decision = "needs_confirmation"
            approved = False
            required_action = "request_user_confirmation"
        elif action_type == "prediction_market_order_execute":
            assert payload["user_confirmed"] is True
            assert payload["metadata"]["execution_ready"] is True
            decision = "approved"
            approved = True
            required_action = None
        else:
            raise AssertionError(f"unexpected action_type {action_type}")
        return {
            "policy_decision_id": f"policy_{action_type}",
            "action_id": payload["action_id"],
            "approved": approved,
            "decision": decision,
            "reason_code": "APPROVED" if approved else "USER_CONFIRMATION_REQUIRED",
            "required_action": required_action,
            "reasons": ["fake policy"],
            **payload,
        }

    def write_audit_event(self, payload: dict) -> dict:
        self.audit_types.append(payload["event_type"])
        return {"event_id": f"audit_{payload['event_type']}", **payload}


class FakePolymarketExecutor(ExecutionAdapter):
    platform = "polymarket"

    def readiness(self) -> PlatformExecutionResult:
        return PlatformExecutionResult(platform="polymarket", ready=True, missing=[], warnings=[])

    def submit_order(self, preview: PredictionMarketOrderPreview) -> PlatformExecutionResult:
        return PlatformExecutionResult(
            platform="polymarket",
            ready=True,
            submitted=True,
            order_id="0xcore_loop_order",
            tx_hash="0xcore_loop_tx",
            status="matched",
        )


class FakeAccountBindingGateway:
    def latest_polymarket_binding(self, user_id: str) -> dict:
        assert user_id == "core-loop-user"
        return {
            "binding_id": "binding-core-loop",
            "user_id": user_id,
            "status": "active",
            "wallet_address": "0x" + "22" * 20,
            "funder_address": "0x" + "11" * 20,
            "polymarket_deposit_wallet": "0x" + "11" * 20,
            "account_mode": "deposit_wallet",
            "polymarket_signature_type": "3",
        }


class FakeAccountIdentityGateway:
    def active_wallet(self, user_id: str) -> str:
        assert user_id == "core-loop-user"
        return "0x" + "22" * 20


class FakeFundingGateway:
    def get_funding_readiness(
        self,
        *,
        user_id: str,
        platform: str,
        amount_usd: str,
        funding_operation_id: str | None,
        binding_id: str,
        venue_wallet_address: str,
    ) -> dict:
        assert user_id == "core-loop-user"
        assert platform == "polymarket"
        assert amount_usd == "1"
        assert funding_operation_id == "funding-core-loop"
        assert binding_id == "binding-core-loop"
        assert venue_wallet_address == "0x" + "11" * 20
        return {
            "ready": True,
            "status": "ready",
            "funding_operation_id": funding_operation_id,
            "funding_proof": {
                "operation_id": funding_operation_id,
                "user_id": user_id,
                "binding_id": binding_id,
                "venue_wallet_address": venue_wallet_address,
                "bridge_address": "0x" + "44" * 20,
                "status": "finalized",
                "amount_usdc": "1.000000",
                "resource": "polygon:usdc",
                "core_state": "finalized",
                "bridge_status": "COMPLETED",
                "venue_buying_power_before_atomic": "0",
                "venue_buying_power_after_atomic": "1000000",
                "reservation_id": "reservation-core-loop",
                "audit_event_id": "audit-core-loop",
                "core_tx_hash": "0x" + "44" * 32,
            },
        }


def _config() -> AppConfig:
    config = AppConfig.from_env()
    config.live_mode = True
    config.require_user_confirmation = True
    config.preview_file = "/tmp/clink_prediction_core_loop_previews.jsonl"
    config.execution_file = "/tmp/clink_prediction_core_loop_executions.jsonl"
    return config


def main() -> None:
    Path("/tmp/clink_prediction_core_loop_previews.jsonl").unlink(missing_ok=True)
    Path("/tmp/clink_prediction_core_loop_executions.jsonl").unlink(missing_ok=True)
    core = RecordingCoreGateway()
    config = _config()
    preview_service = PreviewService(config=config, core_gateway=core)
    market = UnifiedMarket(
        platform="polymarket",
        market_id="558934",
        title="Will Spain win the 2026 FIFA World Cup?",
        yes_price=0.124,
        no_price=0.876,
        liquidity_usd=7710000,
        tradable=True,
        execution_ready=True,
        raw={"orderMinSize": "5"},
    )
    preview = preview_service.create_order_preview(
        CreateOrderPreviewRequest(
            user_id="core-loop-user",
            agent_id="hermes_agent",
            market=market,
            outcome="Yes",
            side="buy",
            amount_usd="1",
            live_mode=True,
            metadata={"funding_operation_id": "funding-core-loop"},
        )
    )
    assert preview.state == "confirmation_required"
    assert preview.core_action_id == "act_prediction_market_order_preview"
    assert preview.core_policy_decision_id == "policy_prediction_market_order_preview"

    execution_service = ExecutionService(
        config=config,
        preview_store=preview_service,
        executors={"polymarket": FakePolymarketExecutor()},
        core_gateway=core,
        funding_gateway=FakeFundingGateway(),
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=FakeAccountIdentityGateway(),
    )
    execution = execution_service.execute_order_preview(
        ExecutePredictionMarketOrderRequest(
            preview_id=preview.preview_id,
            user_confirmed=True,
            live_submission_confirmed=True,
        )
    )
    assert execution.state == "submitted"
    assert execution.submitted is True
    assert execution.core_action_id == "act_prediction_market_order_execute"
    assert execution.core_policy_decision_id == "policy_prediction_market_order_execute"
    assert "prediction_market_order_preview" in core.action_types
    assert "prediction_market_order_execute" in core.action_types
    assert "prediction_market_preview_requested" in core.audit_types
    assert "prediction_market_execution_policy_evaluated" in core.audit_types

    print(
        json.dumps(
            {
                "status": "ok",
                "preview_id": preview.preview_id,
                "execution_id": execution.execution_id,
                "action_types": core.action_types,
                "audit_types": core.audit_types,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
